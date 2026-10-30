import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException

from forecast import (
    BOARD_TARGET, build_forecast, calculate_expected_value, read_clean_table,
)
from pipeline.config import AS_OF_DATE, OUTPUT_ROOT, TARGET_PERIOD

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from pipeline.validation import probability_from_gpa

from movements import build_movements


app = FastAPI(title="PulseFlow Forecast API")
logger = logging.getLogger(__name__)


def load_baseline_tables():
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

    return pointer, current, hubspot, scorecard


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/baseline")
def baseline():
    try:
        pointer, current, hubspot, scorecard = load_baseline_tables()
        forecast_deals, group_summary = build_forecast(
            current, hubspot, scorecard
        )

        # Lookups retain the underlying stage probability for demotion.
        source_records = {
            **{
                f"salesforce:{row['sf_match_key']}": row
                for row in current.to_dict("records")
            },
            **{
                f"hubspot:{row['HubSpot_Deal_ID']}": row
                for row in hubspot.to_dict("records")
            },
        }

        scores = {
            f"salesforce:{row['resolved_sf_match_key']}": row
            for row in scorecard.to_dict("records")
        }

        deals = []

        for row in forecast_deals.to_dict("records"):
            deal_key = row["deal_key"]
            original = source_records[deal_key]
            score = scores.get(deal_key)
            is_salesforce = row["source"] == "salesforce"
            warnings = []

            if original["stale_close_date"] == "True":
                warnings.append("Open deal has a past expected close date.")

            if original.get("cross_system_counterpart_id"):
                warnings.append(
                    "Shared CRM deal; Salesforce retained by explicit mapping."
                )

            if score and (
                float(score["Win_Probability"])
                != float(score["baseline_win_probability"])
            ):
                warnings.append(
                    "Stored VP probability differs from the calculated baseline."
                )

            deals.append({
                "deal_key": deal_key,
                "source": row["source"],
                "customer": row["customer"],
                "product": row["product"],
                "sales_rep": row["sales_rep"],
                "forecast_group": row["forecast_group"],
                "is_strategic": score is not None,
                "annual_acv": float(row["annual_acv"]),
                "probability": float(row["probability"]),
                "expected_value": float(row["expected_value"]),
                "stage": original[
                    "Stage" if is_salesforce else "Deal_Stage"
                ],
                "stage_probability": float(original["Stage_Probability"]),
                "close_date": original[
                    "Close_Date" if is_salesforce else "Expected_Close_Date"
                ],
                "scores": {
                    "leadership": int(float(score["Leadership_Score"])),
                    "commercial": int(float(score["Commercial_Score"])),
                    "contractual": int(float(score["Contractual_Score"])),
                } if score else None,
                "composite_gpa": (
                    float(score["calculated_gpa"]) if score else None
                ),
                "stored_vp_probability": (
                    float(score["Win_Probability"]) if score else None
                ),
                "vp_notes": score["VP_Notes"] if score else None,
                "warnings": warnings,
            })

        def group_value(name):
            if name not in group_summary.index:
                return 0.0
            return float(group_summary.loc[name, "expected_value"])

        strategic = group_value("Strategic")
        salesforce_longtail = group_value("Salesforce longtail")
        hubspot_longtail = group_value("HubSpot longtail")
        total_decimal = sum(
            (Decimal(str(value)) for value in [
                strategic, salesforce_longtail, hubspot_longtail
            ]),
            Decimal(0),
        )
        total = float(total_decimal)

        return {
            "run_id": pointer["run_id"],
            "data_processed_at": pointer["finished_at"],
            "as_of_date": AS_OF_DATE.date().isoformat(),
            "fiscal_period": TARGET_PERIOD,
            "summary": {
                "total_expected_sales": total,
                "strategic_expected_value": strategic,
                "longtail_expected_value": (
                    float(Decimal(str(salesforce_longtail)) + Decimal(str(hubspot_longtail)))
                ),
                "salesforce_longtail_expected_value": salesforce_longtail,
                "hubspot_longtail_expected_value": hubspot_longtail,
                "board_target": BOARD_TARGET,
                "variance_to_target": float(total_decimal - BOARD_TARGET),
                "target_attainment": float(total_decimal / BOARD_TARGET),
                "eligible_deal_count": len(deals),
                "strategic_deal_count": len(scores),
            },
            "filters": {
                "products": sorted({deal["product"] for deal in deals}),
                "sales_reps": sorted({deal["sales_rep"] for deal in deals}),
            },
            "deals": deals,
        }

    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Unable to build baseline response")
        raise HTTPException(
            status_code=503,
            detail=(
                "Baseline data is unavailable or invalid. "
                "Run ingestion successfully and check the server logs."
            ),
        ) from None

Score = Annotated[int, Field(strict=True, ge=1, le=4)]


class StrategicDealInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deal_key: str = Field(min_length=1)
    leadership: Score = 3
    commercial: Score = 3
    contractual: Score = 3


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    strategic_deals: list[StrategicDealInput] = Field(max_length=8)


@app.post("/api/scenario")
def scenario(request: ScenarioRequest):
    # Load one consistent baseline snapshot for this request.
    baseline_data = baseline()

    if request.run_id != baseline_data["run_id"]:
        raise HTTPException(
            status_code=409,
            detail="Baseline data changed. Reload before editing the scenario.",
        )

    selected = {
        deal.deal_key: deal
        for deal in request.strategic_deals
    }

    if len(selected) != len(request.strategic_deals):
        raise HTTPException(
            status_code=422,
            detail="A deal cannot appear more than once in the strategic list.",
        )

    eligible_keys = {
        deal["deal_key"] for deal in baseline_data["deals"]
    }
    unknown_keys = sorted(set(selected) - eligible_keys)

    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Strategic selection contains unknown or ineligible deals.",
                "deal_keys": unknown_keys,
            },
        )

    result = deepcopy(baseline_data)

    totals = {
        "Strategic": Decimal("0"),
        "Salesforce longtail": Decimal("0"),
        "HubSpot longtail": Decimal("0"),
    }
    changed_count = 0

    for deal in result["deals"]:
        original_scores = deal["scores"]
        original_strategic = deal["is_strategic"]
        original_expected = deal["expected_value"]
        selection = selected.get(deal["deal_key"])

        if selection is not None:
            new_scores = {
                "leadership": selection.leadership,
                "commercial": selection.commercial,
                "contractual": selection.contractual,
            }

            gpa = (
                Decimal("0.20") * selection.leadership
                + Decimal("0.20") * selection.commercial
                + Decimal("0.60") * selection.contractual
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Reuse the same probability lookup as cleaning.
            probability = Decimal(str(probability_from_gpa(gpa)))

            deal["is_strategic"] = True
            deal["forecast_group"] = "Strategic"
            deal["scores"] = new_scores
            deal["composite_gpa"] = float(gpa)

        else:
            probability = Decimal(str(deal["stage_probability"]))

            deal["is_strategic"] = False
            deal["forecast_group"] = (
                "Salesforce longtail"
                if deal["source"] == "salesforce"
                else "HubSpot longtail"
            )
            deal["scores"] = None
            deal["composite_gpa"] = None

        expected = calculate_expected_value(deal["annual_acv"], probability)

        deal["probability"] = float(probability)
        deal["expected_value"] = float(expected)
        deal["baseline_expected_value"] = original_expected
        deal["expected_value_change"] = float(
            expected - Decimal(str(original_expected))
        )

        deal["is_modified"] = (
            deal["is_strategic"] != original_strategic
            or deal["scores"] != original_scores
        )

        changed_count += int(deal["is_modified"])
        totals[deal["forecast_group"]] += expected

    strategic = totals["Strategic"]
    sf_longtail = totals["Salesforce longtail"]
    hs_longtail = totals["HubSpot longtail"]
    total = strategic + sf_longtail + hs_longtail
    target = Decimal(str(BOARD_TARGET))
    baseline_total = Decimal(
        str(baseline_data["summary"]["total_expected_sales"])
    )

    result["summary"] = {
        "total_expected_sales": float(total),
        "strategic_expected_value": float(strategic),
        "longtail_expected_value": float(sf_longtail + hs_longtail),
        "salesforce_longtail_expected_value": float(sf_longtail),
        "hubspot_longtail_expected_value": float(hs_longtail),
        "board_target": BOARD_TARGET,
        "variance_to_target": float(total - target),
        "target_attainment": float(total / target),
        "eligible_deal_count": len(result["deals"]),
        "strategic_deal_count": len(selected),
    }

    result["scenario"] = {
        "is_modified": changed_count > 0,
        "modified_deal_count": changed_count,
        "baseline_expected_sales": float(baseline_total),
        "impact": float(total - baseline_total),
    }

    return result

@app.get("/api/movements")
def movements():
    try:
        pointer = json.loads(
            (OUTPUT_ROOT / "latest_successful_run.json").read_text(
                encoding="utf-8"
            )
        )

        if pointer["status"] != "succeeded" or not pointer["outputs_ready"]:
            raise ValueError("Cleaning outputs are not ready.")

        run_dir = Path(pointer["output_directory"])

        current = read_clean_table(
            run_dir, "salesforce_current_clean.csv"
        )
        prior = read_clean_table(
            run_dir, "salesforce_prior_clean.csv"
        )

        events, missing = build_movements(current, prior)

        categories = [
            "New deal",
            "Slipped to Q1-2027",
            "Closed Lost",
            "Stage move",
            "ACV change",
        ]

        counts = {
            category: int(events["category"].eq(category).sum())
            for category in categories
        }

        acv_changes = events.loc[
            events["category"].eq("ACV change"), "acv_change"
        ]

        return {
            "run_id": pointer["run_id"],
            "data_processed_at": pointer["finished_at"],
            "as_of_date": AS_OF_DATE.date().isoformat(),
            "fiscal_period": TARGET_PERIOD,
            "counts": counts,
            "net_acv_change": float(acv_changes.sum()),
            # DataFrame JSON conversion handles missing values as null.
            "events": json.loads(events.to_json(orient="records")),
            "missing_from_current": json.loads(
                missing.to_json(orient="records")
            ),
            "notes": [
                "A deal may appear in multiple movement categories.",
                "New means newly present in the Salesforce export.",
                "Stage and ACV changes apply to currently active Q4 deals.",
                "ACV changes are unweighted contract values, not forecast changes.",
            ],
        }

    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Unable to build movement response")
        raise HTTPException(
            status_code=503,
            detail=(
                "Movement data is unavailable or invalid. "
                "Run ingestion successfully and check the server logs."
            ),
        ) from None

@app.get("/api/audit")
def audit():
    try:
        pointer = json.loads(
            (OUTPUT_ROOT / "latest_successful_run.json").read_text(
                encoding="utf-8"
            )
        )

        if pointer["status"] != "succeeded" or not pointer["outputs_ready"]:
            raise ValueError("Cleaning outputs are not ready.")

        run_dir = Path(pointer["output_directory"])
        table = read_clean_table(run_dir, "audit_log.csv")

        required_columns = {
            "event_id",
            "source_file",
            "source_row",
            "column",
            "raw_value",
            "issue",
            "status",
            "resolution",
            "reason",
        }

        missing = required_columns - set(table.columns)
        if missing:
            raise ValueError(
                f"Audit columns are missing: {sorted(missing)}"
            )

        if table["event_id"].eq("").any() or table["event_id"].duplicated().any():
            raise ValueError("Audit event IDs are missing or duplicated.")

        status_labels = {
            "resolved": "Resolved",
            "accepted_assumption": "Accepted assumption",
            "business_review": "Business review",
            "baseline_rule_applied": "Baseline rule applied",
            "excluded_from_forecast": "Excluded from forecast",
            "requires_review": "Requires review",
        }

        counts = {
            status: int(table["status"].eq(status).sum())
            for status in status_labels
        }

        unknown_statuses = set(table["status"]) - set(status_labels)
        if unknown_statuses:
            raise ValueError(
                f"Unknown audit statuses: {sorted(unknown_statuses)}"
            )

        events = []

        for record in table.to_dict("records"):
            # Blank optional cells become JSON null.
            event = {
                key: None if value == "" else value
                for key, value in record.items()
            }

            # These fields represent source locations or removal counts.
            for column in [
                "source_row",
                "selected_source_row",
                "rows_removed",
                "columns_removed",
            ]:
                if event.get(column) is not None:
                    event[column] = int(float(event[column]))

            event["status_label"] = status_labels[event["status"]]
            events.append(event)

        return {
            "run_id": pointer["run_id"],
            "data_processed_at": pointer["finished_at"],
            "as_of_date": AS_OF_DATE.date().isoformat(),
            "summary": {
                "total_events": len(events),
                "counts_by_status": counts,
                "requires_review_count": counts["requires_review"],
                "business_review_count": counts["business_review"],
                "accepted_assumption_events": counts["accepted_assumption"],
            },
            "filters": {
                "source_files": sorted(
                    table.loc[
                        table["source_file"].ne(""), "source_file"
                    ].unique().tolist()
                ),
                "statuses": [
                    {"value": status, "label": label}
                    for status, label in status_labels.items()
                    if counts[status] > 0
                ],
            },
            "events": events,
            "notes": [
                "Counts represent audit events, not unique data problems.",
                "Detection and resolution may appear as separate events.",
                "Accepted assumptions are documented decisions, not verified facts.",
                "Business-review warnings remain visible after cleaning succeeds.",
            ],
        }

    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        logger.exception("Unable to build audit response")
        raise HTTPException(
            status_code=503,
            detail=(
                "Audit data is unavailable or invalid. "
                "Run ingestion successfully and check the server logs."
            ),
        ) from None
