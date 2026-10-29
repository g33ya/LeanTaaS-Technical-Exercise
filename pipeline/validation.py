"""Validate schemas, field values, rules, and readiness."""
import math
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

from .config import (AS_OF_DATE, TARGET_PERIOD, OPEN_STAGES, STAGE_PROBABILITIES, VALID_PRODUCTS)
from .schemas import SCHEMAS


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
