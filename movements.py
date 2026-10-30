import json
from pathlib import Path

import pandas as pd

from pipeline.config import OUTPUT_ROOT, TARGET_PERIOD


STAGE_ORDER = {
    "Introduction": 1,
    "Technical Validation": 2,
    "Business Approval": 3,
    "Contract Negotiations": 4,
}


def build_movements(current, prior):
    current = current.copy()
    prior = prior.copy()

    for label, table in [("Current", current), ("Prior", prior)]:
        keys = table["sf_match_key"]

        if keys.eq("").any() or keys.isna().any() or keys.duplicated().any():
            raise ValueError(f"{label}: missing or duplicate Salesforce keys.")

        table["Annual_ACV"] = pd.to_numeric(
            table["Annual_ACV"], errors="raise"
        )

        valid_acv = (
            table["Annual_ACV"].notna()
            & table["Annual_ACV"].ge(0)
            & table["Annual_ACV"].lt(float("inf"))
        )
        if not valid_acv.all():
            raise ValueError(f"{label}: invalid annual ACV.")

        if not table["Stage"].isin([*STAGE_ORDER, "Closed Lost"]).all():
            raise ValueError(f"{label}: unsupported Salesforce stage.")

    comparison = current.merge(
        prior,
        on="sf_match_key",
        how="outer",
        suffixes=("_current", "_prior"),
        validate="one_to_one",
        indicator=True,
    )

    def event(row, category, direction=""):
        in_current = row["_merge"] != "right_only"
        in_prior = row["_merge"] != "left_only"

        return {
            "sf_match_key": row["sf_match_key"],
            "customer": (
                row["Health_System_current"]
                if in_current else row["Health_System_prior"]
            ),
            "category": category,
            "direction": direction,
            "prior_period": row["Fiscal_Period_prior"] if in_prior else None,
            "current_period": (
                row["Fiscal_Period_current"] if in_current else None
            ),
            "prior_stage": row["Stage_prior"] if in_prior else None,
            "current_stage": row["Stage_current"] if in_current else None,
            "prior_acv": row["Annual_ACV_prior"] if in_prior else None,
            "current_acv": row["Annual_ACV_current"] if in_current else None,
            "acv_change": (
                row["Annual_ACV_current"] - row["Annual_ACV_prior"]
                if in_current and in_prior else None
            ),
        }

    events = []
    missing_from_current = []

    for _, row in comparison.iterrows():
        presence = row["_merge"]

        if presence == "left_only":
            # New means newly present in Salesforce, regardless of quarter.
            events.append(event(row, "New deal"))
            continue

        if presence == "right_only":
            # Absence alone does not establish that a deal was lost.
            missing_from_current.append(
                event(row, "Missing from current export")
            )
            continue

        prior_stage = row["Stage_prior"]
        current_stage = row["Stage_current"]

        if (
            row["Fiscal_Period_prior"] == TARGET_PERIOD
            and row["Fiscal_Period_current"] == "Q1-2027"
        ):
            events.append(event(row, "Slipped to Q1-2027"))

        if prior_stage in STAGE_ORDER and current_stage == "Closed Lost":
            events.append(event(row, "Closed Lost"))

        # Stage and ACV changes apply to currently active Q4 deals.
        active_q4 = (
            row["Fiscal_Period_current"] == TARGET_PERIOD
            and current_stage in STAGE_ORDER
        )

        if not active_q4:
            continue

        if prior_stage in STAGE_ORDER and prior_stage != current_stage:
            direction = (
                "Advanced"
                if STAGE_ORDER[current_stage] > STAGE_ORDER[prior_stage]
                else "Regressed"
            )
            events.append(event(row, "Stage move", direction))

        if row["Annual_ACV_current"] != row["Annual_ACV_prior"]:
            direction = (
                "Expansion"
                if row["Annual_ACV_current"] > row["Annual_ACV_prior"]
                else "Contraction"
            )
            events.append(event(row, "ACV change", direction))

    columns = [
        "sf_match_key", "customer", "category", "direction",
        "prior_period", "current_period", "prior_stage", "current_stage",
        "prior_acv", "current_acv", "acv_change",
    ]

    return (
        pd.DataFrame(events, columns=columns),
        pd.DataFrame(missing_from_current, columns=columns),
    )


def main():
    pointer = json.loads(
        (OUTPUT_ROOT / "latest_successful_run.json").read_text(
            encoding="utf-8"
        )
    )

    if pointer["status"] != "succeeded" or not pointer["outputs_ready"]:
        raise ValueError("Cleaning outputs are not ready.")

    run_dir = Path(pointer["output_directory"])

    def read(filename):
        return pd.read_csv(
            run_dir / filename,
            dtype="string",
            keep_default_na=False,
            encoding="utf-8-sig",
        )

    movements, missing = build_movements(
        read("salesforce_current_clean.csv"),
        read("salesforce_prior_clean.csv"),
    )

    print(f"Using cleaning run: {pointer['run_id']}\n")

    categories = [
        "New deal",
        "Slipped to Q1-2027",
        "Closed Lost",
        "Stage move",
        "ACV change",
    ]

    counts = (
        movements["category"]
        .value_counts()
        .reindex(categories, fill_value=0)
    )
    print(counts.to_string())

    for category in categories:
        print(f"\n{category}:")
        print(
            movements.loc[movements["category"].eq(category)].to_string(
                index=False,
                float_format=lambda value: f"{value:,.0f}",
            )
        )

    if not missing.empty:
        print("\nReview: records missing from the current export:")
        print(missing.to_string(index=False))


if __name__ == "__main__":
    main()