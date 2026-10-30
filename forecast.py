import json
from pathlib import Path

import pandas as pd

from pipeline.config import OUTPUT_ROOT


BOARD_TARGET = 12_000_000


def read_clean_table(run_dir, filename):
    table = pd.read_csv(
        run_dir / filename,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    return table


def build_forecast(current, hubspot, scorecard):
    # Work only with eligible records.
    sf = current.loc[current["forecast_eligible"].eq("True")].copy()
    hs = hubspot.loc[hubspot["forecast_eligible"].eq("True")].copy()

    if sf["sf_match_key"].duplicated().any():
        raise ValueError("Eligible Salesforce keys are not unique.")

    if hs["HubSpot_Deal_ID"].duplicated().any():
        raise ValueError("Eligible HubSpot IDs are not unique.")

    strategic_keys = scorecard["resolved_sf_match_key"]

    if strategic_keys.eq("").any() or strategic_keys.duplicated().any():
        raise ValueError("Strategic keys are missing or duplicated.")

    if not set(strategic_keys).issubset(set(sf["sf_match_key"])):
        raise ValueError("A strategic deal is missing from eligible Salesforce.")

    # Attach the scorecard probability to current Salesforce records.
    strategic = sf.loc[sf["sf_match_key"].isin(strategic_keys)].merge(
        scorecard[
            ["resolved_sf_match_key", "baseline_win_probability"]
        ],
        left_on="sf_match_key",
        right_on="resolved_sf_match_key",
        how="inner",
        validate="one_to_one",
    )

    sf_longtail = sf.loc[
        ~sf["sf_match_key"].isin(strategic_keys)
    ].copy()

    def prepare(table, source, group, id_column, name_column, probability_column):
        result = pd.DataFrame({
            "deal_key": source + ":" + table[id_column],
            "source": source,
            "forecast_group": group,
            "customer": table[name_column],
            "product": table["Product"],
            "sales_rep": table[
                "Sales_Rep" if source == "salesforce" else "AE_Owner"
            ],
            "annual_acv": pd.to_numeric(table["Annual_ACV"], errors="raise"),
            "probability": pd.to_numeric(
                table[probability_column], errors="raise"
            ),
        })

        valid_acv = (
            result["annual_acv"].notna()
            & result["annual_acv"].ge(0)
            & result["annual_acv"].lt(float("inf"))
        )
        valid_probability = result["probability"].between(0, 1)

        if not (valid_acv & valid_probability).all():
            raise ValueError(f"{group}: invalid ACV or probability.")

        result["expected_value"] = (
            result["annual_acv"] * result["probability"]
        )
        return result

    deals = pd.concat(
        [
            prepare(
                strategic, "salesforce", "Strategic",
                "sf_match_key", "Health_System",
                "baseline_win_probability",
            ),
            prepare(
                sf_longtail, "salesforce", "Salesforce longtail",
                "sf_match_key", "Health_System", "Stage_Probability",
            ),
            prepare(
                hs, "hubspot", "HubSpot longtail",
                "HubSpot_Deal_ID", "Company_Name", "Stage_Probability",
            ),
        ],
        ignore_index=True,
    )

    # Verify exact coverage, not just the total count.
    expected_keys = (
        {"salesforce:" + key for key in sf["sf_match_key"]}
        | {"hubspot:" + key for key in hs["HubSpot_Deal_ID"]}
    )

    if (
        deals["deal_key"].duplicated().any()
        or set(deals["deal_key"]) != expected_keys
    ):
        raise ValueError("Eligible deals are missing or counted more than once.")

    summary = deals.groupby("forecast_group", sort=False).agg(
        deal_count=("deal_key", "size"),
        annual_acv=("annual_acv", "sum"),
        expected_value=("expected_value", "sum"),
    )

    return deals, summary


def main():
    pointer = json.loads(
        (OUTPUT_ROOT / "latest_successful_run.json").read_text(
            encoding="utf-8"
        )
    )

    if pointer["status"] != "succeeded" or not pointer["outputs_ready"]:
        raise ValueError("Cleaning outputs are not ready.")

    run_dir = Path(pointer["output_directory"])

    current = read_clean_table(run_dir, "salesforce_current_clean.csv")
    hubspot = read_clean_table(run_dir, "hubspot_clean.csv")
    scorecard = read_clean_table(run_dir, "strategic_scorecard_clean.csv")

    deals, summary = build_forecast(current, hubspot, scorecard)

    total = deals["expected_value"].sum()
    variance = total - BOARD_TARGET

    print(f"Using cleaning run: {pointer['run_id']}\n")
    print(summary.to_string(float_format=lambda value: f"{value:,.2f}"))
    print(f"\nEligible deals: {len(deals)}")
    print(f"Total expected Q4 sales: ${total:,.2f}")
    print(f"Board target: ${BOARD_TARGET:,.2f}")
    print(f"Variance to target: ${variance:,.2f}")


if __name__ == "__main__":
    main()