from pathlib import Path
import pandas as pd
from schemas import SCHEMAS
from conflict_overrides import CONFLICT_OVERRIDES
from scorecard_id_overrides import SCORECARD_ID_OVERRIDES
from pipeline_errors import PipelineValidationError
import math
from decimal import Decimal, ROUND_HALF_UP

BASE_DIR = Path(__file__).resolve().parent
# Available to the runner if a stage fails.
all_issues = []

SOURCE_COLUMNS = {"source_file", "source_sheet", "source_row"}

CROSS_SYSTEM_MAPPINGS = [
    {
        "salesforce_id": "006PF000001M001YAC",
        "hubspot_id": "HS-9001",
        "reason": (
            "Assumed same deal based on matching customer, product, owner, "
            "close date, equivalent stage, and annual ACV. "
            "Salesforce retained as the forecast source."
        ),
    },
]

HUBSPOT_STAGE_TO_SF = {
    "Introduction": "Introduction",
    "Qualified to Buy": "Technical Validation",
    "Decision Maker Bought-In": "Business Approval",
    "Contract Sent": "Contract Negotiations",
    "Closed Lost": "Closed Lost",
}

AS_OF_DATE = pd.Timestamp("2026-10-15")

TARGET_PERIOD = "Q4-2026"

OPEN_STAGES = {
    "salesforce": {
        "Introduction",
        "Technical Validation",
        "Business Approval",
        "Contract Negotiations",
    },
    "hubspot": {
        "Introduction",
        "Qualified to Buy",
        "Decision Maker Bought-In",
        "Contract Sent",
    },
}

STAGE_PROBABILITIES = {
    "salesforce": {
        "Introduction": 0.20,
        "Technical Validation": 0.40,
        "Business Approval": 0.60,
        "Contract Negotiations": 0.80,
        "Closed Lost": 0.00,
    },
    "hubspot": {
        "Introduction": 0.20,
        "Qualified to Buy": 0.40,
        "Decision Maker Bought-In": 0.60,
        "Contract Sent": 0.80,
        "Closed Lost": 0.00,
    },
}

VALID_PRODUCTS = {"PulseOR", "BedFlow", "InfusionIQ", "CareBridge"}


def load_csv(file_path):
    file_path = Path(file_path)
    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path

    # Keep identifiers and other raw values as strings.
    df = pd.read_csv(
        file_path,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8-sig",
        skip_blank_lines=False,
    )

    # Treat whitespace-only cells as empty when checking export padding.
    empty_cells = df.apply(lambda column: column.str.strip().eq(""))

    empty_rows = empty_cells.all(axis=1)
    empty_columns = [
        column
        for column in df.columns
        if column.startswith("Unnamed:") and empty_cells[column].all()
    ]

    issues = [
        {
            "source_file": file_path.name,
            "issue": "Empty export padding removed",
            "rows_removed": int(empty_rows.sum()),
            "columns_removed": len(empty_columns),
        }
    ]

    # Header is row 1, so the first data record is row 2.
    df.insert(0, "source_row", range(2, len(df) + 2))
    df.insert(0, "source_file", file_path.name)

    df = df.loc[~empty_rows].drop(columns=empty_columns).copy()
    df = df.reset_index(drop=True)

    return df, issues


def load_scorecard(file_path):
    file_path = Path(file_path)
    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path

    df = pd.read_excel(
        file_path,
        sheet_name="Top 8 Scorecard",
        header=3,  # Zero-based: Excel row 4 contains the headers.
        dtype="string",
        keep_default_na=False,
        engine="openpyxl",
    )

    empty_cells = df.apply(lambda column: column.str.strip().eq(""))
    empty_rows = empty_cells.all(axis=1)

    empty_columns = [
        column
        for column in df.columns
        if column.startswith("Unnamed:") and empty_cells[column].all()
    ]

    issues = [
        {
            "source_file": file_path.name,
            "source_sheet": "Top 8 Scorecard",
            "issue": "Empty export padding removed",
            "rows_removed": int(empty_rows.sum()),
            "columns_removed": len(empty_columns),
        }
    ]

    # The first data record is on Excel row 5.
    df.insert(0, "source_row", range(5, len(df) + 5))
    df.insert(0, "source_sheet", "Top 8 Scorecard")
    df.insert(0, "source_file", file_path.name)

    df = df.loc[~empty_rows].drop(columns=empty_columns).copy()
    df = df.reset_index(drop=True)

    return df, issues


def validate_table(raw_df, table_type):
    schema = SCHEMAS[table_type]
    source_file = raw_df["source_file"].iloc[0] if len(raw_df) else table_type

    missing_columns = [
        column for column in schema["required"]
        if column not in raw_df.columns
    ]
    if missing_columns:
        raise ValueError(
            f"{source_file}: missing required columns: "
            f"{', '.join(missing_columns)}"
        )

    df = raw_df.copy()
    issues = []

    def report(mask, column, issue):
        for index in df.index[mask]:
            issues.append({
                "source_file": df.at[index, "source_file"],
                "source_sheet": (
                    df.at[index, "source_sheet"]
                    if "source_sheet" in df.columns else None
                ),
                "source_row": int(df.at[index, "source_row"]),
                "column": column,
                "raw_value": raw_df.at[index, column],
                "issue": issue,
            })

    # Normalize whitespace and missing values in the working copy.
    for column in schema["required"]:
        values = df[column].astype("string")
        trimmed = values.str.strip()

        changed = values.ne(trimmed).fillna(False)
        report(changed, column, "Surrounding whitespace removed")

        df[column] = trimmed.replace("", pd.NA)

    # Check missing values in fields needed for identification/calculation.
    optional_fields = {
        "scorecard": {"VP_Notes"},
    }.get(table_type, set())

    for column in schema["required"]:
        if column not in optional_fields:
            report(
                df[column].isna(),
                column,
                "Missing value; requires review",
            )

    # Convert numbers explicitly, recording conversion failures.
    for column in schema["numeric"]:
        original = df[column]
        converted = pd.to_numeric(original, errors="coerce")

        report(
            original.notna() & converted.isna(),
            column,
            "Invalid number; converted to missing",
        )
        df[column] = converted

    # Parse each source's known date format.
    for column, date_format in schema["dates"].items():
        original = df[column]
        converted = pd.to_datetime(
            original,
            format=date_format,
            errors="coerce",
        )

        report(
            original.notna() & converted.isna(),
            column,
            "Invalid date; converted to missing",
        )
        df[column] = converted

    # Basic numeric constraints.
    for column in ["Stage_Probability", "Win_Probability"]:
        if column in schema["numeric"]:
            report(
                df[column].notna() & ~df[column].between(0, 1),
                column,
                "Probability must be between 0 and 1",
            )

    if "Amount" in schema["numeric"]:
        report(df["Amount"].lt(0).fillna(False), "Amount", "Negative amount")

    for column in ["Leadership_Score", "Commercial_Score", "Contractual_Score"]:
        if column in schema["numeric"]:
            valid_score = df[column].isin([1, 2, 3, 4])
            report(
                df[column].notna() & ~valid_score,
                column,
                "Score must be an integer from 1 to 4",
            )

    if "Days_In_Stage" in schema["numeric"]:
        values = df["Days_In_Stage"]
        invalid = values.notna() & (
            values.lt(0) | values.mod(1).ne(0)
        )
        report(
            invalid.fillna(False),
            "Days_In_Stage",
            "Days in stage must be a nonnegative integer",
        )

    return df, issues


def check_duplicates(df, id_column):
    df = df.copy()
    issues = []

    # Source locations differ even when the business records are identical.
    business_columns = [
        column for column in df.columns
        if column not in SOURCE_COLUMNS
    ]

    def log_issue(row, issue, **details):
        issues.append({
            "source_file": row["source_file"],
            "source_sheet": row.get("source_sheet", None),
            "source_row": int(row["source_row"]),
            "column": id_column,
            "raw_value": row[id_column],
            "issue": issue,
            **details,
        })

    # Only deduplicate records that have an ID.
    has_id = (
        df[id_column].notna()
        & df[id_column].astype("string").str.strip().ne("").fillna(False)
    )

    exact_duplicates = pd.Series(False, index=df.index)
    exact_duplicates.loc[has_id] = df.loc[has_id].duplicated(
        subset=business_columns,
        keep="first",
    )

    for _, row in df.loc[exact_duplicates].iterrows():
        log_issue(
            row,
            "Exact duplicate removed; first occurrence retained",
        )

    df = df.loc[~exact_duplicates].copy()

    # After exact duplicates are removed, repeated IDs indicate conflicts.
    has_id = (
        df[id_column].notna()
        & df[id_column].astype("string").str.strip().ne("").fillna(False)
    )

    conflicting = (
        has_id
        & df[id_column].duplicated(keep=False)
    )

    for _, group in df.loc[conflicting].groupby(id_column, sort=False):
        differing_columns = [
            column for column in business_columns
            if group[column].nunique(dropna=False) > 1
        ]

        for _, row in group.iterrows():
            log_issue(
                row,
                "Conflicting duplicate ID; retained for review",
                differing_columns=", ".join(differing_columns),
            )

    return df.reset_index(drop=True), issues


def add_salesforce_match_key(df, id_column, allowed_lengths):
    df = df.copy()
    issues = []

    ids = df[id_column].astype("string")

    present = ids.notna() & ids.str.strip().ne("").fillna(False)
    valid = (
        present
        & ids.str.len().isin(allowed_lengths)
        & ids.str.fullmatch(r"[A-Za-z0-9]+", na=False)
    )

    # Preserve case. Missing or malformed IDs receive no matching key.
    df["sf_match_key"] = ids.str.slice(0, 15).where(valid, pd.NA)

    for index in df.index[present & ~valid]:
        issues.append({
            "source_file": df.at[index, "source_file"],
            "source_sheet": (
                df.at[index, "source_sheet"]
                if "source_sheet" in df.columns else None
            ),
            "source_row": int(df.at[index, "source_row"]),
            "column": id_column,
            "raw_value": ids.at[index],
            "issue": (
                "Invalid Salesforce ID format; expected an alphanumeric "
                f"ID of length {sorted(allowed_lengths)}"
            ),
        })

    return df, issues


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


def annualize_amounts(df):
    df = df.copy()
    issues = []

    # Normalize only for comparison; preserve the original frequency column.
    frequency = (
        df["Billing_Frequency"]
        .astype("string")
        .str.strip()
        .str.casefold()
    )

    multiplier = frequency.map({"annual": 1, "monthly": 12})
    amount = pd.to_numeric(df["Amount"], errors="coerce")

    valid_amount = amount.notna() & amount.ge(0) & amount.lt(float("inf"))

    df["Annual_ACV"] = (amount * multiplier).where(
        valid_amount & multiplier.notna()
    )

    for index in df.index:
        problems = []

        if pd.isna(multiplier.at[index]):
            problems.append("Missing or unsupported billing frequency")

        if not valid_amount.at[index]:
            problems.append("Missing, invalid, negative, or infinite amount")

        if problems:
            issues.append({
                "source_file": df.at[index, "source_file"],
                "source_sheet": (
                    df.at[index, "source_sheet"]
                    if "source_sheet" in df.columns else None
                ),
                "source_row": int(df.at[index, "source_row"]),
                "column": "Annual_ACV",
                "raw_value": (
                    f"Amount={df.at[index, 'Amount']}; "
                    f"Billing_Frequency={df.at[index, 'Billing_Frequency']}"
                ),
                "issue": "; ".join(problems),
                "resolution": "Annual_ACV left missing; requires review",
            })

    return df, issues


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


def mark_forecast_eligibility(df, source_type):
    df = df.copy()
    issues = []

    if source_type == "salesforce":
        stage_column = "Stage"
        date_column = "Close_Date"
    elif source_type == "hubspot":
        stage_column = "Deal_Stage"
        date_column = "Expected_Close_Date"
    else:
        raise ValueError(f"Unsupported source type: {source_type}")

    dates = df[date_column]
    stages = df[stage_column]

    # Compare the declared period with the calendar quarter of the close date.
    date_period = pd.Series(pd.NA, index=df.index, dtype="string")
    has_date = dates.notna()
    date_period.loc[has_date] = (
        "Q"
        + dates.loc[has_date].dt.quarter.astype("string")
        + "-"
        + dates.loc[has_date].dt.year.astype("string")
    )

    df["close_date_period"] = date_period
    df["period_date_conflict"] = (
        df["Fiscal_Period"].notna()
        & date_period.notna()
        & df["Fiscal_Period"].ne(date_period)
    ).fillna(False)

    is_open = stages.isin(OPEN_STAGES[source_type])

    df["stale_close_date"] = (
        is_open & dates.lt(AS_OF_DATE)
    ).fillna(False)

    exclusion_reasons = []

    def log_issue(index, column, issue, resolution):
        issues.append({
            "source_file": df.at[index, "source_file"],
            "source_row": int(df.at[index, "source_row"]),
            "column": column,
            "raw_value": df.at[index, column],
            "issue": issue,
            "resolution": resolution,
        })

    for index, row in df.iterrows():
        reasons = []

        included = row["include_in_combined"]
        if pd.isna(included) or not bool(included):
            reasons.append("Not selected for combined forecast")

        period = row["Fiscal_Period"]
        if pd.isna(period):
            reasons.append("Missing fiscal period")
        elif period != TARGET_PERIOD:
            reasons.append("Outside Q4-2026")

        stage = row[stage_column]
        if pd.isna(stage) or stage not in OPEN_STAGES[source_type]:
            if pd.notna(stage) and stage == "Closed Lost":
                reasons.append("Closed Lost")
            else:
                reasons.append("Missing or unsupported stage")
                log_issue(
                    index,
                    stage_column,
                    "Missing or unsupported stage",
                    "Excluded pending review",
                )

        if pd.isna(row[date_column]):
            reasons.append("Missing or invalid close date")

        if row["period_date_conflict"]:
            reasons.append("Fiscal period and close date disagree")
            log_issue(
                index,
                "Fiscal_Period",
                f"Fiscal period disagrees with close-date period "
                f"{row['close_date_period']}",
                "Excluded pending review",
            )

        acv = row["Annual_ACV"]
        if pd.isna(acv) or acv < 0 or acv == float("inf"):
            reasons.append("Missing or invalid annual ACV")

        if row["stale_close_date"]:
            log_issue(
                index,
                date_column,
                "Open deal has a close date before 2026-10-15",
                "Flagged for review; stale date alone does not exclude deal",
            )

        exclusion_reasons.append("; ".join(reasons))

    df["exclusion_reason"] = exclusion_reasons
    df["forecast_eligible"] = df["exclusion_reason"].eq("")

    return df, issues


def validate_stage_probabilities(df, source_type):
    df = df.copy()
    issues = []

    stage_column = (
        "Stage" if source_type == "salesforce" else "Deal_Stage"
    )

    df["expected_stage_probability"] = df[stage_column].map(
        STAGE_PROBABILITIES[source_type]
    )
    df["stage_probability_matches"] = False

    for index, row in df.iterrows():
        expected = row["expected_stage_probability"]
        actual = row["Stage_Probability"]

        matches = (
            pd.notna(expected)
            and pd.notna(actual)
            and math.isclose(
                float(actual),
                float(expected),
                rel_tol=0,
                abs_tol=1e-9,
            )
        )

        df.at[index, "stage_probability_matches"] = matches

        if not matches:
            issues.append({
                "source_file": row["source_file"],
                "source_row": int(row["source_row"]),
                "column": "Stage_Probability",
                "raw_value": actual,
                "expected_value": expected,
                "issue": (
                    "Unknown stage; probability cannot be checked"
                    if pd.isna(expected)
                    else "Stage probability disagrees with stage mapping"
                ),
                "resolution": (
                    "Exported probability preserved; Closed Lost remains "
                    "excluded by eligibility rules. Open mismatches need review."
                ),
            })

    return df, issues


def probability_from_gpa(gpa):
    if gpa >= Decimal("3.20"):
        return 0.75
    if gpa >= Decimal("2.40"):
        return 0.50
    if gpa >= Decimal("1.60"):
        return 0.30
    return 0.10


def validate_scorecard_probabilities(df):
    df = df.copy()
    issues = []

    df["calculated_gpa"] = pd.Series(
        pd.NA, index=df.index, dtype="Float64"
    )
    df["baseline_win_probability"] = pd.Series(
        pd.NA, index=df.index, dtype="Float64"
    )

    score_columns = [
        "Leadership_Score",
        "Commercial_Score",
        "Contractual_Score",
    ]

    def log_issue(row, column, expected, issue, resolution):
        issues.append({
            "source_file": row["source_file"],
            "source_sheet": row["source_sheet"],
            "source_row": int(row["source_row"]),
            "column": column,
            "raw_value": row[column],
            "expected_value": expected,
            "issue": issue,
            "resolution": resolution,
        })

    for index, row in df.iterrows():
        scores = [row[column] for column in score_columns]

        if any(
            pd.isna(score) or score not in [1, 2, 3, 4]
            for score in scores
        ):
            log_issue(
                row,
                "Composite_GPA",
                None,
                "Cannot calculate GPA: missing or invalid score",
                "Baseline GPA and probability left missing; requires review",
            )
            continue

        leadership, commercial, contractual = [
            Decimal(str(score)) for score in scores
        ]

        gpa = (
            Decimal("0.20") * leadership
            + Decimal("0.20") * commercial
            + Decimal("0.60") * contractual
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        probability = probability_from_gpa(gpa)

        df.at[index, "calculated_gpa"] = float(gpa)
        df.at[index, "baseline_win_probability"] = probability

        for column, expected in [
            ("Composite_GPA", float(gpa)),
            ("Win_Probability", probability),
        ]:
            actual = row[column]
            matches = (
                pd.notna(actual)
                and math.isclose(
                    float(actual),
                    expected,
                    rel_tol=0,
                    abs_tol=1e-9,
                )
            )

            if not matches:
                log_issue(
                    row,
                    column,
                    expected,
                    "Stored scorecard value disagrees with deterministic rules",
                    "Stored value preserved; calculated value used for baseline",
                )

    return df, issues


def validate_categories_and_keys(df, source_type):
    issues = []

    def report(index, column, issue):
        issues.append({
            "source_file": df.at[index, "source_file"],
            "source_row": int(df.at[index, "source_row"]),
            "column": column,
            "raw_value": df.at[index, column],
            "issue": issue,
            "severity": "error",
            "resolution": "Requires review before forecast calculations",
        })

    checks = {
        "Product": df["Product"].isin(VALID_PRODUCTS),
        "Billing_Frequency": (
            df["Billing_Frequency"]
            .astype("string")
            .str.strip()
            .str.casefold()
            .isin(["annual", "monthly"])
        ),
        "Fiscal_Period": (
            df["Fiscal_Period"]
            .astype("string")
            .str.fullmatch(r"Q[1-4]-[0-9]{4}", na=False)
        ),
    }

    stage_column = "Stage" if source_type == "salesforce" else "Deal_Stage"
    checks[stage_column] = df[stage_column].isin(
        STAGE_PROBABILITIES[source_type]
    )

    for column, valid in checks.items():
        for index in df.index[~valid.fillna(False)]:
            report(index, column, "Missing or unsupported category")

    key_column = (
        "sf_match_key" if source_type == "salesforce"
        else "HubSpot_Deal_ID"
    )

    missing_key = (
        df[key_column].isna()
        | df[key_column].astype("string").str.strip().eq("").fillna(False)
    )

    for index in df.index[missing_key]:
        report(index, key_column, "Missing deal key")

    duplicate_key = (
        ~missing_key
        & df[key_column].duplicated(keep=False)
    )

    for index in df.index[duplicate_key]:
        report(
            index,
            key_column,
            "Duplicate deal key remains after cleaning",
        )

    return issues


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


def check_cleaning_readiness(current_df, prior_df, hubspot_df, scorecard_df):
    problems = []

    for label, table, key_column in [
        ("Current Salesforce", current_df, "sf_match_key"),
        ("Prior Salesforce", prior_df, "sf_match_key"),
        ("HubSpot", hubspot_df, "HubSpot_Deal_ID"),
    ]:
        if table.empty:
            problems.append(f"{label}: table is empty")

        if table[key_column].isna().any():
            problems.append(f"{label}: missing deal keys")

        if table[key_column].duplicated().any():
            problems.append(f"{label}: duplicate deal keys")

        # These fields are needed for reconciliation and movement analysis,
        # including records excluded from the forecast.
        for column in ["Fiscal_Period", "Product", "Annual_ACV"]:
            if table[column].isna().any():
                problems.append(f"{label}: missing {column}")

    for label, table, stage_column, date_column in [
        ("Current Salesforce", current_df, "Stage", "Close_Date"),
        ("HubSpot", hubspot_df, "Deal_Stage", "Expected_Close_Date"),
    ]:
        eligible = table.loc[table["forecast_eligible"].fillna(False)]

        for _, row in eligible.iterrows():
            location = f"{label}, source row {row['source_row']}"

            if row["Fiscal_Period"] != TARGET_PERIOD:
                problems.append(f"{location}: eligible outside target period")

            if row[stage_column] not in (
                OPEN_STAGES[
                    "salesforce" if label == "Current Salesforce" else "hubspot"
                ]
            ):
                problems.append(f"{location}: eligible with unsupported stage")

            if not row["include_in_combined"]:
                problems.append(f"{location}: excluded duplicate is eligible")

            if pd.isna(row[date_column]) or row["period_date_conflict"]:
                problems.append(f"{location}: unresolved close-date issue")

            acv = row["Annual_ACV"]
            if (
                pd.isna(acv)
                or not math.isfinite(float(acv))
                or acv < 0
            ):
                problems.append(f"{location}: invalid annual ACV")

        # Strategic probabilities come from the scorecard.
        # Only longtail deals require a valid exported stage probability.
        longtail = eligible
        if label == "Current Salesforce":
            strategic_keys = set(scorecard_df["resolved_sf_match_key"])
            longtail = eligible.loc[
                ~eligible["sf_match_key"].isin(strategic_keys)
            ]

        for _, row in longtail.iterrows():
            probability = row["Stage_Probability"]

            if (
                pd.isna(probability)
                or not 0 <= probability <= 1
                or not row["stage_probability_matches"]
            ):
                problems.append(
                    f"{label}, source row {row['source_row']}: "
                    "unresolved longtail probability"
                )

    if scorecard_df.empty or len(scorecard_df) > 8:
        problems.append("Scorecard must contain between 1 and 8 strategic deals")

    if problems:
        raise ValueError(
            "Cleaning readiness checks failed:\n- "
            + "\n- ".join(problems)
        )

    print("Cleaning readiness checks passed.")


def build_audit_log(events, current_checked, hubspot_checked):
    audit = pd.DataFrame(events).copy()

    if audit.empty:
        return audit

    # Ensure optional fields exist across the different event types.
    for column in [
        "source_file", "source_sheet", "source_row", "column",
        "raw_value", "issue", "resolution", "reason",
    ]:
        if column not in audit.columns:
            audit[column] = pd.NA

    audit["source_row"] = pd.to_numeric(
        audit["source_row"], errors="coerce"
    ).astype("Int64")

    audit["status"] = "requires_review"

    def location(row):
        return (
            row["source_file"],
            None if pd.isna(row["source_sheet"]) else row["source_sheet"],
            None if pd.isna(row["source_row"]) else int(row["source_row"]),
        )

    # Link earlier findings to later resolution events by source location.
    id_resolutions = {}
    conflict_resolutions = {}

    for _, row in audit.iterrows():
        if row["issue"] == "Missing scorecard ID resolved by explicit mapping":
            id_resolutions[location(row)] = row.get(
                "resolved_sf_match_key"
            )
        elif row["issue"] in {
            "Conflict resolved: version selected by override",
            "Conflict resolved: version excluded by override",
        }:
            conflict_resolutions[location(row)] = row["reason"]

    for index, row in audit.iterrows():
        issue = row["issue"]
        row_location = location(row)

        if issue in {
            "Empty export padding removed",
            "Surrounding whitespace removed",
            "Exact duplicate removed; first occurrence retained",
        }:
            audit.at[index, "status"] = "resolved"

        elif issue == "Missing scorecard ID resolved by explicit mapping":
            audit.at[index, "status"] = "resolved"

        elif (
            issue == "Missing value; requires review"
            and row["column"] == "Opportunity_ID_15"
            and row_location in id_resolutions
        ):
            audit.at[index, "status"] = "resolved"
            audit.at[index, "resolution"] = (
                f"Resolved by explicit mapping to "
                f"{id_resolutions[row_location]}"
            )

        elif issue in {
            "Conflict resolved: version selected by override",
            "Conflict resolved: version excluded by override",
            "Cross-system duplicate: retained for combined forecast",
            "Cross-system duplicate: excluded from combined forecast",
        }:
            audit.at[index, "status"] = "accepted_assumption"

        elif (
            issue == "Conflicting duplicate ID; retained for review"
            and row_location in conflict_resolutions
        ):
            audit.at[index, "status"] = "accepted_assumption"
            audit.at[index, "resolution"] = conflict_resolutions[row_location]

        elif issue == "Open deal has a close date before 2026-10-15":
            audit.at[index, "status"] = "business_review"

        elif issue == "Stored scorecard value disagrees with deterministic rules":
            audit.at[index, "status"] = "baseline_rule_applied"

        elif issue == "Stage probability disagrees with stage mapping":
            # Confirm from the final tables that the deal is Closed Lost
            # and excluded, rather than treating every mismatch as harmless.
            closed_lost_excluded = False

            for table, stage_column in [
                (current_checked, "Stage"),
                (hubspot_checked, "Deal_Stage"),
            ]:
                matches = table.loc[
                    table["source_file"].eq(row["source_file"])
                    & table["source_row"].eq(row["source_row"])
                ]

                if len(matches) == 1:
                    record = matches.iloc[0]
                    closed_lost_excluded = (
                        record[stage_column] == "Closed Lost"
                        and not record["forecast_eligible"]
                    )
                    break

            if closed_lost_excluded:
                audit.at[index, "status"] = "excluded_from_forecast"

    audit.insert(
        0,
        "event_id",
        [f"AUDIT-{number:04d}" for number in range(1, len(audit) + 1)],
    )

    return audit


def main(output_dir=None):
    """Load, clean, reconcile, validate, and export one data drop."""
    global all_issues
    all_issues = []

    current, current_issues = load_csv("1_sfdc_pipeline_current.csv")

    prior, prior_issues = load_csv("2_sfdc_pipeline_prior_week.csv")

    hubspot, hubspot_issues = load_csv("4_carebridge_hubspot_export.csv")

    print(f"Current Salesforce: {len(current)} records")

    print(f"Prior Salesforce: {len(prior)} records")

    print(f"HubSpot: {len(hubspot)} records")

    print(pd.DataFrame(current_issues + prior_issues).to_string(index=False))

    scorecard, scorecard_issues = load_scorecard("3_vp_deal_scorecard.xlsx")

    probability_rules = pd.read_excel(
        BASE_DIR / "3_vp_deal_scorecard.xlsx",
        sheet_name="GPA Probability Rules",
        header=2,
        dtype="string",
        keep_default_na=False,
        engine="openpyxl",
    )

    probability_rules_issues = []

    probability_rules.insert(
        0, "source_row", range(4, len(probability_rules) + 4)
    )

    probability_rules.insert(0, "source_sheet", "GPA Probability Rules")

    probability_rules.insert(0, "source_file", "3_vp_deal_scorecard.xlsx")

    print(f"HubSpot: {len(hubspot)} records")

    print(f"VP scorecard: {len(scorecard)} records")

    print(f"Probability rules: {len(probability_rules)} rows")

    all_issues = (
        current_issues
        + prior_issues
        + hubspot_issues
        + scorecard_issues
        + probability_rules_issues
    )

    current_clean, current_validation = validate_table(current, "salesforce")

    prior_clean, prior_validation = validate_table(prior, "salesforce")

    hubspot_clean, hubspot_validation = validate_table(hubspot, "hubspot")

    scorecard_clean, scorecard_validation = validate_table(scorecard, "scorecard")

    rules_clean, rules_validation = validate_table(probability_rules, "probability_rules")

    validation_issues = (
        current_validation
        + prior_validation
        + hubspot_validation
        + scorecard_validation
        + rules_validation
    )

    all_issues = all_issues + validation_issues

    if validation_issues:
        print(pd.DataFrame(validation_issues).to_string(index=False))
    else:
        print("Schema and field-type checks passed.")

    current_clean, current_duplicate_issues = check_duplicates(
        current_clean, "Opportunity_ID"
    )

    prior_clean, prior_duplicate_issues = check_duplicates(
        prior_clean, "Opportunity_ID"
    )

    hubspot_clean, hubspot_duplicate_issues = check_duplicates(
        hubspot_clean, "HubSpot_Deal_ID"
    )

    scorecard_clean, scorecard_duplicate_issues = check_duplicates(
        scorecard_clean, "Opportunity_ID_15"
    )

    duplicate_issues = (
        current_duplicate_issues
        + prior_duplicate_issues
        + hubspot_duplicate_issues
        + scorecard_duplicate_issues
    )

    all_issues = all_issues + duplicate_issues

    print(f"Current Salesforce: {len(current_clean)} rows")

    print(f"Prior Salesforce: {len(prior_clean)} rows")

    print(f"HubSpot: {len(hubspot_clean)} rows")

    print(f"VP scorecard: {len(scorecard_clean)} rows")

    if duplicate_issues:
        print(pd.DataFrame(duplicate_issues).to_string(index=False))
    else:
        print("No duplicates found.")

    current_clean, current_id_issues = add_salesforce_match_key(
        current_clean,
        "Opportunity_ID",
        allowed_lengths={15, 18},
    )

    prior_clean, prior_id_issues = add_salesforce_match_key(
        prior_clean,
        "Opportunity_ID",
        allowed_lengths={15, 18},
    )

    scorecard_clean, scorecard_id_issues = add_salesforce_match_key(
        scorecard_clean,
        "Opportunity_ID_15",
        allowed_lengths={15},
    )

    id_issues = (
        current_id_issues
        + prior_id_issues
        + scorecard_id_issues
    )

    all_issues = all_issues + id_issues

    for label, table in [
        ("Current Salesforce", current_clean),
        ("Prior Salesforce", prior_clean),
        ("VP scorecard", scorecard_clean),
    ]:
        print(
            f"{label}: {table['sf_match_key'].notna().sum()} matching keys, "
            f"{table['sf_match_key'].isna().sum()} missing"
        )

    if id_issues:
        print(pd.DataFrame(id_issues).to_string(index=False))
    else:
        print("All populated Salesforce IDs passed format checks.")

    current_resolved, resolution_issues = resolve_conflicts(
        current_clean,
        CONFLICT_OVERRIDES,
    )

    all_issues = all_issues + resolution_issues

    print(f"Current before resolution: {len(current_clean)} rows")

    print(f"Current after resolution: {len(current_resolved)} rows")

    if resolution_issues:
        print(pd.DataFrame(resolution_issues).to_string(index=False))

    scorecard_matched, scorecard_match_issues = match_scorecard(
        scorecard_clean,
        current_resolved,
        SCORECARD_ID_OVERRIDES,
    )

    all_issues = all_issues + scorecard_match_issues

    print(f"Matched scorecard rows: {len(scorecard_matched)}")

    print(scorecard_matched[
        [
            "Hospital_Shorthand_Name",
            "resolved_sf_match_key",
            "match_method",
            "sf_Health_System",
        ]
    ].to_string(index=False))

    current_resolved, current_acv_issues = annualize_amounts(current_resolved)

    prior_clean, prior_acv_issues = annualize_amounts(prior_clean)

    hubspot_clean, hubspot_acv_issues = annualize_amounts(hubspot_clean)

    acv_issues = current_acv_issues + prior_acv_issues + hubspot_acv_issues

    all_issues = all_issues + acv_issues

    for label, table in [
        ("Current Salesforce", current_resolved),
        ("Prior Salesforce", prior_clean),
        ("HubSpot", hubspot_clean),
    ]:
        print(
            f"{label}: {table['Annual_ACV'].notna().sum()} annualized, "
            f"{table['Annual_ACV'].isna().sum()} unresolved"
        )

    if acv_issues:
        print(pd.DataFrame(acv_issues).to_string(index=False))

    print(current_resolved.loc[
        current_resolved["Opportunity_ID"].eq("006PF000001M001YAC"),
        ["Opportunity_ID", "Amount", "Billing_Frequency", "Annual_ACV"],
    ].to_string(index=False))

    print(hubspot_clean.loc[
        hubspot_clean["HubSpot_Deal_ID"].eq("HS-9001"),
        ["HubSpot_Deal_ID", "Amount", "Billing_Frequency", "Annual_ACV"],
    ].to_string(index=False))

    current_reconciled, hubspot_reconciled, reconciliation_issues = (
        reconcile_cross_system(
            current_resolved,
            hubspot_clean,
            CROSS_SYSTEM_MAPPINGS,
        )
    )

    all_issues = all_issues + reconciliation_issues

    print(
        "Salesforce included:",
        int(current_reconciled["include_in_combined"].sum()),
    )

    print(
        "HubSpot included:",
        int(hubspot_reconciled["include_in_combined"].sum()),
    )

    if reconciliation_issues:
        print(pd.DataFrame(reconciliation_issues).to_string(index=False))

    current_eligible, current_eligibility_issues = mark_forecast_eligibility(
        current_reconciled, "salesforce"
    )

    hubspot_eligible, hubspot_eligibility_issues = mark_forecast_eligibility(
        hubspot_reconciled, "hubspot"
    )

    eligibility_issues = (
        current_eligibility_issues + hubspot_eligibility_issues
    )

    all_issues = all_issues + eligibility_issues

    for label, table in [
        ("Salesforce", current_eligible),
        ("HubSpot", hubspot_eligible),
    ]:
        print(
            f"{label}: "
            f"{int(table['forecast_eligible'].sum())} eligible, "
            f"{int(table['stale_close_date'].sum())} stale close dates"
        )

    if eligibility_issues:
        print(pd.DataFrame(eligibility_issues).to_string(index=False))

    current_checked, current_probability_issues = validate_stage_probabilities(
        current_eligible, "salesforce"
    )

    prior_checked, prior_probability_issues = validate_stage_probabilities(
        prior_clean, "salesforce"
    )

    hubspot_checked, hubspot_probability_issues = validate_stage_probabilities(
        hubspot_eligible, "hubspot"
    )

    scorecard_checked, scorecard_probability_issues = (
        validate_scorecard_probabilities(scorecard_matched)
    )

    probability_issues = (
        current_probability_issues
        + prior_probability_issues
        + hubspot_probability_issues
        + scorecard_probability_issues
    )

    all_issues = all_issues + probability_issues

    if probability_issues:
        print(pd.DataFrame(probability_issues).to_string(index=False))
    else:
        print("All probability checks passed.")

    print(scorecard_checked[
        [
            "Hospital_Shorthand_Name",
            "Composite_GPA",
            "calculated_gpa",
            "Win_Probability",
            "baseline_win_probability",
        ]
    ].to_string(index=False))

    category_key_issues = (
        validate_categories_and_keys(current_checked, "salesforce")
        + validate_categories_and_keys(prior_checked, "salesforce")
        + validate_categories_and_keys(hubspot_checked, "hubspot")
    )

    all_issues = all_issues + category_key_issues

    if category_key_issues:
        print(pd.DataFrame(category_key_issues).to_string(index=False))
        raise ValueError(
            "Category or key validation failed. Review the issues above."
        )
    else:
        print("Category and deal-key checks passed for all three pipeline tables.")

    scorecard_ready = refresh_scorecard_salesforce(
        scorecard_checked,
        current_checked,
    )

    print(f"Strategic deals ready: {len(scorecard_ready)}")

    print(scorecard_ready[
        [
            "Hospital_Shorthand_Name",
            "resolved_sf_match_key",
            "sf_Annual_ACV",
            "sf_forecast_eligible",
            "calculated_gpa",
            "baseline_win_probability",
        ]
    ].to_string(index=False))

    check_cleaning_readiness(
        current_checked,
        prior_checked,
        hubspot_checked,
        scorecard_ready,
    )

    audit_log = build_audit_log(all_issues, current_checked, hubspot_checked)

    print("\nAudit event counts:")

    print(audit_log["status"].value_counts().to_string())

    unresolved = audit_log.loc[audit_log["status"].eq("requires_review")]

    if not unresolved.empty:
        print(unresolved.to_string(index=False))
        raise ValueError(
            "Unresolved audit findings remain. Review them before saving outputs."
        )

    output_dir = Path(output_dir) if output_dir is not None else BASE_DIR / "outputs"

    output_dir.mkdir(parents=True, exist_ok=True)

    prepared_tables = {
        "salesforce_current_clean.csv": current_checked,
        "salesforce_prior_clean.csv": prior_checked,
        "hubspot_clean.csv": hubspot_checked,
        "strategic_scorecard_clean.csv": scorecard_ready,
        "probability_rules_clean.csv": rules_clean,
        "audit_log.csv": audit_log,
    }

    for filename, table in prepared_tables.items():
        table.to_csv(
            output_dir / filename,
            index=False,
            encoding="utf-8-sig",
            date_format="%Y-%m-%d",
        )

    print(f"\nSaved {len(prepared_tables)} files to: {output_dir}")


if __name__ == "__main__":
    main()
