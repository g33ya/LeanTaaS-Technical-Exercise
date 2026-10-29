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