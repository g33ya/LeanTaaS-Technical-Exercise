"""Combine findings and link them to recorded resolutions."""
import pandas as pd


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

        elif (
            issue == "Open deal has a close date before 2026-10-15"
            or row.get("issue_code") == "STAGE_AGE_NOT_RESET"
        ):
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
