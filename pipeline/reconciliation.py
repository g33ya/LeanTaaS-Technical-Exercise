"""Resolve conflicts and match records across sources."""
import math
from decimal import Decimal

import pandas as pd

from .config import HUBSPOT_STAGE_TO_SF
from .errors import PipelineValidationError
from .validation import probability_from_gpa


def resolve_conflicts(df, overrides, key_column="sf_match_key"):
    result = df.copy()
    issues = []
    rows_to_remove = []

    # Index overrides by source and deal key.
    override_lookup = {}
    for override in overrides:
        key = (override["source_file"], override["match_key"])

        if key in override_lookup:
            raise ValueError(f"Multiple overrides configured for {key}")

        override_lookup[key] = override

    # Missing keys need identity review before conflict resolution.
    if result[key_column].isna().any():
        raise ValueError(
            "Cannot resolve conflicts while matching keys are missing."
        )

    group_columns = ["source_file", key_column]
    duplicated = result.duplicated(subset=group_columns, keep=False)

    for key, group in result.loc[duplicated].groupby(
        group_columns, sort=False
    ):
        override = override_lookup.get(key)

        if override is None:
            conflict_findings = []
            for _, row in group.iterrows():
                conflict_findings.append({
                    "source_file": row["source_file"],
                    "source_sheet": row.get("source_sheet", None),
                    "source_row": int(row["source_row"]),
                    "column": key_column,
                    "raw_value": row[key_column],
                    "issue_code": "UNRESOLVED_CONFLICT",
                    "status": "requires_review",
                    "issue": "Conflicting records have no configured resolution",
                })

            raise PipelineValidationError(
                f"Unresolved conflict for {key}. "
                "Add an explicit override before continuing.",
                issues=issues + conflict_findings,
            )

        if not override.get("select") or not override.get("reason", "").strip():
            raise ValueError(
                f"Override for {key} needs selection fields and a reason."
            )

        matches = pd.Series(True, index=group.index)

        for column, expected_value in override["select"].items():
            if column not in group.columns:
                raise ValueError(
                    f"Override for {key} references unknown column: {column}"
                )

            matches &= group[column].eq(expected_value).fillna(False)

        if int(matches.sum()) != 1:
            raise ValueError(
                f"Override for {key} matched {int(matches.sum())} rows; "
                "expected exactly one. Review the current data."
            )

        selected_index = group.index[matches][0]
        selected_row = int(group.at[selected_index, "source_row"])

        for index, row in group.iterrows():
            selected = index == selected_index

            issues.append({
                "source_file": row["source_file"],
                "source_sheet": row.get("source_sheet", None),
                "source_row": int(row["source_row"]),
                "column": key_column,
                "raw_value": row[key_column],
                "issue": (
                    "Conflict resolved: version selected by override"
                    if selected
                    else "Conflict resolved: version excluded by override"
                ),
                "selected_source_row": selected_row,
                "reason": override["reason"],
            })

            if not selected:
                rows_to_remove.append(index)

    result = result.drop(index=rows_to_remove).reset_index(drop=True)
    return result, issues


def match_scorecard(scorecard_df, salesforce_df, overrides):
    scorecard = scorecard_df.copy()
    salesforce = salesforce_df.copy()
    issues = []

    # Salesforce must contain one record per matching key.
    if salesforce["sf_match_key"].isna().any():
        raise ValueError("Salesforce contains missing matching keys.")

    if salesforce["sf_match_key"].duplicated().any():
        raise ValueError(
            "Salesforce contains duplicate matching keys. "
            "Resolve conflicts before matching the scorecard."
        )

    # Preserve the original key, including blanks.
    scorecard["resolved_sf_match_key"] = scorecard["sf_match_key"]
    scorecard["match_method"] = "provided_id"
    scorecard["match_reason"] = "Matched using the provided Salesforce ID."

    for index in scorecard.index[
        scorecard["resolved_sf_match_key"].isna()
    ]:
        name = scorecard.at[index, "Hospital_Shorthand_Name"]
        override = overrides.get(name)

        if override is None:
            raise ValueError(
                f"No ID mapping configured for scorecard customer: {name}"
            )

        scorecard.at[index, "resolved_sf_match_key"] = override["sf_match_key"]
        scorecard.at[index, "match_method"] = "explicit_mapping"
        scorecard.at[index, "match_reason"] = override["reason"]

    if scorecard["resolved_sf_match_key"].duplicated().any():
        raise ValueError(
            "Multiple scorecard rows resolve to the same opportunity."
        )

    # Prefix Salesforce fields to preserve both sources and their locations.
    sf_lookup = salesforce.add_prefix("sf_")

    matched = scorecard.merge(
        sf_lookup,
        left_on="resolved_sf_match_key",
        right_on="sf_sf_match_key",
        how="left",
        validate="one_to_one",
        indicator=True,
    )

    unmatched = matched["_merge"].ne("both")
    if unmatched.any():
        names = matched.loc[
            unmatched, "Hospital_Shorthand_Name"
        ].tolist()
        raise ValueError(f"Scorecard rows not found in Salesforce: {names}")

    # These fields should agree even when customer names use shorthand.
    for column in ["Product", "Sales_Rep"]:
        agrees = matched[column].eq(matched[f"sf_{column}"]).fillna(False)

        if not agrees.all():
            names = matched.loc[
                ~agrees, "Hospital_Shorthand_Name"
            ].tolist()
            raise ValueError(
                f"{column} mismatch between scorecard and Salesforce: {names}"
            )

    for _, row in matched.loc[
        matched["match_method"].eq("explicit_mapping")
    ].iterrows():
        issues.append({
            "source_file": row["source_file"],
            "source_sheet": row["source_sheet"],
            "source_row": int(row["source_row"]),
            "column": "Opportunity_ID_15",
            "raw_value": row["Opportunity_ID_15"],
            "issue": "Missing scorecard ID resolved by explicit mapping",
            "resolved_sf_match_key": row["resolved_sf_match_key"],
            "reason": row["match_reason"],
        })

    matched = matched.drop(columns=["_merge", "sf_sf_match_key"])
    return matched, issues


def reconcile_cross_system(sf_df, hs_df, mappings):
    sf = sf_df.copy()
    hs = hs_df.copy()
    issues = []

    # This flag controls duplicate inclusion only, not forecast eligibility.
    sf["include_in_combined"] = True
    hs["include_in_combined"] = True

    sf["cross_system_counterpart_id"] = pd.Series(
        pd.NA, index=sf.index, dtype="string"
    )
    hs["cross_system_counterpart_id"] = pd.Series(
        pd.NA, index=hs.index, dtype="string"
    )

    seen_sf = set()
    seen_hs = set()

    for mapping in mappings:
        sf_id = mapping["salesforce_id"]
        hs_id = mapping["hubspot_id"]

        if sf_id in seen_sf or hs_id in seen_hs:
            raise ValueError("Cross-system mappings must be one-to-one.")

        seen_sf.add(sf_id)
        seen_hs.add(hs_id)

        sf_matches = sf.index[sf["Opportunity_ID"].eq(sf_id).fillna(False)]
        hs_matches = hs.index[hs["HubSpot_Deal_ID"].eq(hs_id).fillna(False)]

        if len(sf_matches) != 1 or len(hs_matches) != 1:
            raise ValueError(
                f"Mapping {sf_id} / {hs_id} requires exactly one "
                "record in each source."
            )

        sf_index = sf_matches[0]
        hs_index = hs_matches[0]
        sf_row = sf.loc[sf_index]
        hs_row = hs.loc[hs_index]

        comparisons = {
            "customer": (
                sf_row["Health_System"], hs_row["Company_Name"]
            ),
            "product": (
                sf_row["Product"], hs_row["Product"]
            ),
            "owner": (
                sf_row["Sales_Rep"], hs_row["AE_Owner"]
            ),
            "close date": (
                sf_row["Close_Date"], hs_row["Expected_Close_Date"]
            ),
            "fiscal period": (
                sf_row["Fiscal_Period"], hs_row["Fiscal_Period"]
            ),
            "stage": (
                sf_row["Stage"],
                HUBSPOT_STAGE_TO_SF.get(hs_row["Deal_Stage"]),
            ),
            "stage probability": (
                sf_row["Stage_Probability"],
                hs_row["Stage_Probability"],
            ),
            "annual ACV": (
                sf_row["Annual_ACV"], hs_row["Annual_ACV"]
            ),
        }

        disagreements = [
            field
            for field, (sf_value, hs_value) in comparisons.items()
            if (
                pd.isna(sf_value)
                or pd.isna(hs_value)
                or sf_value != hs_value
            )
        ]

        if disagreements:
            raise ValueError(
                f"Cross-system mapping {sf_id} / {hs_id} failed "
                f"validation: {', '.join(disagreements)}. Review before merging."
            )

        sf.at[sf_index, "cross_system_counterpart_id"] = hs_id
        hs.at[hs_index, "cross_system_counterpart_id"] = sf_id
        hs.at[hs_index, "include_in_combined"] = False

        for row, id_column, action, counterpart in [
            (
                sf_row, "Opportunity_ID",
                "Cross-system duplicate: retained for combined forecast",
                hs_id,
            ),
            (
                hs_row, "HubSpot_Deal_ID",
                "Cross-system duplicate: excluded from combined forecast",
                sf_id,
            ),
        ]:
            issues.append({
                "source_file": row["source_file"],
                "source_row": int(row["source_row"]),
                "column": id_column,
                "raw_value": row[id_column],
                "issue": action,
                "counterpart_id": counterpart,
                "reason": mapping["reason"],
            })

    return sf, hs, issues


def refresh_scorecard_salesforce(scorecard_df, salesforce_df):
    # Remove fields from the earlier Salesforce join.
    old_sf_columns = [
        column for column in scorecard_df.columns
        if column.startswith("sf_")
    ]
    scorecard = scorecard_df.drop(columns=old_sf_columns).copy()

    if scorecard["resolved_sf_match_key"].isna().any():
        raise ValueError("Scorecard contains unresolved Salesforce keys.")

    if scorecard["resolved_sf_match_key"].duplicated().any():
        raise ValueError("Scorecard contains duplicate resolved keys.")

    if salesforce_df["sf_match_key"].isna().any():
        raise ValueError("Salesforce contains missing matching keys.")

    if salesforce_df["sf_match_key"].duplicated().any():
        raise ValueError("Salesforce contains duplicate matching keys.")

    refreshed = scorecard.merge(
        salesforce_df.add_prefix("sf_"),
        left_on="resolved_sf_match_key",
        right_on="sf_sf_match_key",
        how="left",
        validate="one_to_one",
        indicator=True,
    )

    problems = []

    for _, row in refreshed.iterrows():
        name = row["Hospital_Shorthand_Name"]

        if row["_merge"] != "both":
            problems.append(f"{name}: no Salesforce match")
            continue

        for column in ["Product", "Sales_Rep"]:
            vp_value = row[column]
            sf_value = row[f"sf_{column}"]

            if (
                pd.isna(vp_value)
                or pd.isna(sf_value)
                or vp_value != sf_value
            ):
                problems.append(f"{name}: {column} mismatch")

        eligible = row["sf_forecast_eligible"]
        if pd.isna(eligible) or not bool(eligible):
            problems.append(
                f"{name}: not forecast eligible "
                f"({row['sf_exclusion_reason']})"
            )

        acv = row["sf_Annual_ACV"]
        if pd.isna(acv) or not math.isfinite(float(acv)) or acv < 0:
            problems.append(f"{name}: invalid annual ACV")

        gpa = row["calculated_gpa"]
        probability = row["baseline_win_probability"]

        if pd.isna(gpa) or not 1 <= gpa <= 4:
            problems.append(f"{name}: invalid calculated GPA")
        elif (
            pd.isna(probability)
            or not math.isclose(
                float(probability),
                probability_from_gpa(Decimal(str(gpa))),
                rel_tol=0,
                abs_tol=1e-9,
            )
        ):
            problems.append(f"{name}: invalid baseline probability")

    if problems:
        raise ValueError(
            "Strategic deal readiness checks failed:\n- "
            + "\n- ".join(problems)
        )

    return refreshed.drop(columns=["_merge", "sf_sf_match_key"])
