"""Regression checks for missing probabilities, money rounding, and stage aging."""
import unittest
from decimal import Decimal
from unittest.mock import patch

import pandas as pd

import api.main as api
from forecast import build_forecast, calculate_expected_value
from pipeline.audit import build_audit_log
from pipeline.validation import validate_stage_aging


def tables():
    common = {
        "forecast_eligible": "True", "Product": "PulseOR", "Sales_Rep": "Rep",
        "Stage": "Business Approval", "Stage_Probability": "0.6",
        "Close_Date": "2026-12-01", "stale_close_date": "False",
        "cross_system_counterpart_id": "",
    }
    current = pd.DataFrame([
        dict(common, sf_match_key="S1", Health_System="Strategic", Annual_ACV="100.01"),
        dict(common, sf_match_key="S2", Health_System="Longtail", Annual_ACV="200.03"),
    ], dtype="string")
    hubspot = pd.DataFrame([{
        "forecast_eligible": "True", "HubSpot_Deal_ID": "H1",
        "Company_Name": "Acquired", "Product": "CareBridge", "AE_Owner": "Rep",
        "Deal_Stage": "Qualified to Buy", "Stage_Probability": "0.4",
        "Annual_ACV": "300.01", "Expected_Close_Date": "2026-12-01",
        "stale_close_date": "False", "cross_system_counterpart_id": "",
    }], dtype="string")
    scorecard = pd.DataFrame([{
        "resolved_sf_match_key": "S1", "baseline_win_probability": "0.75",
        "Leadership_Score": "4", "Commercial_Score": "4",
        "Contractual_Score": "3", "calculated_gpa": "3.4",
        "Win_Probability": "0.75", "VP_Notes": "",
    }], dtype="string")
    return current, hubspot, scorecard


class ForecastIntegrityTests(unittest.TestCase):
    def test_missing_probabilities_rejected_in_every_group(self):
        for source in ["salesforce", "hubspot", "scorecard"]:
            for missing in ["", pd.NA]:
                with self.subTest(source=source, missing=missing):
                    current, hubspot, scorecard = tables()
                    if source == "salesforce":
                        current.loc[1, "Stage_Probability"] = missing
                    elif source == "hubspot":
                        hubspot.loc[0, "Stage_Probability"] = missing
                    else:
                        scorecard.loc[0, "baseline_win_probability"] = missing
                    with self.assertRaises(ValueError):
                        build_forecast(current, hubspot, scorecard)

    def test_decimal_rounding_and_invalid_numbers(self):
        self.assertEqual(calculate_expected_value("0.01", "0.5"), Decimal("0.01"))
        self.assertEqual(calculate_expected_value("2400000.01", ".75"), Decimal("1800000.01"))
        for amount, chance in [("NaN", ".5"), ("1", "Infinity"), ("-1", ".5"), ("1", "1.1")]:
            with self.assertRaises(ValueError):
                calculate_expected_value(amount, chance)

    def test_cent_valued_baseline_matches_unchanged_scenario(self):
        current, hubspot, scorecard = tables()
        pointer = {"run_id": "test", "finished_at": "2026-10-15T00:00:00Z"}
        with patch.object(api, "load_baseline_tables", return_value=(pointer, current, hubspot, scorecard)):
            baseline = api.baseline()
            unchanged = api.scenario(api.ScenarioRequest(
                run_id="test", strategic_deals=[{
                    "deal_key": "salesforce:S1", "leadership": 4,
                    "commercial": 4, "contractual": 3,
                }],
            ))
            self.assertEqual(baseline["summary"], unchanged["summary"])
            self.assertEqual(unchanged["scenario"]["impact"], 0)
            self.assertEqual(unchanged["scenario"]["modified_deal_count"], 0)
            self.assertEqual(
                [d["expected_value"] for d in baseline["deals"]],
                [d["expected_value"] for d in unchanged["deals"]],
            )
            promoted = api.scenario(api.ScenarioRequest(
                run_id="test", strategic_deals=[{"deal_key": "hubspot:H1"}],
            ))
            self.assertEqual(promoted["summary"]["strategic_expected_value"], 150.01)

    def test_stage_age_warning_is_nonblocking_and_preserves_values(self):
        current = pd.DataFrame([{
            "sf_match_key": "S1", "Stage": "Business Approval", "Days_In_Stage": 15,
            "source_file": "current.csv", "source_row": 2, "Opportunity_ID": "S1",
        }])
        prior = pd.DataFrame([{
            "sf_match_key": "S1", "Stage": "Technical Validation", "Days_In_Stage": 8,
        }])
        original = current.copy(deep=True)
        issues = validate_stage_aging(current, prior)
        self.assertEqual(len(issues), 1)
        pd.testing.assert_frame_equal(current, original)
        audit = build_audit_log(issues, current, pd.DataFrame())
        self.assertEqual(audit.iloc[0]["status"], "business_review")
        for reset_days in [0, 2]:
            current.loc[0, "Days_In_Stage"] = reset_days
            self.assertEqual(validate_stage_aging(current, prior), [])


if __name__ == "__main__":
    unittest.main()
