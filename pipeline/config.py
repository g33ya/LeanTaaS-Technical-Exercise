"""Shared paths and deterministic business rules."""
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = BASE_DIR / "data" / "raw"
OUTPUT_ROOT = BASE_DIR / "outputs"

SOURCE_COLUMNS = {"source_file", "source_sheet", "source_row"}

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
