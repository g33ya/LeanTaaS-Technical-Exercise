"""Explicit reconciliation decisions and their supporting reasons."""

CONFLICT_OVERRIDES = [
    {
        "source_file": "1_sfdc_pipeline_current.csv",
        "match_key": "006PF000001L008",
        "select": {
            "Stage": "Contract Negotiations",
            "Stage_Probability": 0.8,
            "Amount": 550000,
            "Days_In_Stage": 2,
        },
        "reason": (
            "Assumed updated version: prior week was Business Approval "
            "at $400,000; this version shows advancement and 2 days "
            "in the new stage. No update timestamp is available."
        ),
    },
]
SCORECARD_ID_OVERRIDES = {
    "Ironwood Clinical": {
        "sf_match_key": "006PF000001T005",
        "reason": "Customer name, product, and sales rep support this match.",
    },
    "Borealis Health": {
        "sf_match_key": "006PF000001T006",
        "reason": (
            "VP note specifies Main Campus; product and Clara Oswald "
            "agree. North Surgery Clinic is a separate opportunity."
        ),
    },
    "Starlight Oncology": {
        "sf_match_key": "006PF000001T007",
        "reason": "Customer name, product, and sales rep support this match.",
    },
    "Halcyon Medical": {
        "sf_match_key": "006PF000001T008",
        "reason": (
            "Customer shorthand matches the Salesforce name and alias; "
            "product and sales rep agree."
        ),
    },
}
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
