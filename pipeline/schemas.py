SCHEMAS = {
    "salesforce": {
        "required": [
            "Opportunity_ID", "Fiscal_Period", "Health_System", "Product",
            "Stage", "Stage_Probability", "Amount", "Billing_Frequency",
            "Close_Date", "Created_Date", "Days_In_Stage", "Sales_Rep",
            "Region",
        ],
        "numeric": ["Stage_Probability", "Amount", "Days_In_Stage"],
        "dates": {
            "Close_Date": "%m/%d/%Y",
            "Created_Date": "%m/%d/%Y",
        },
    },
    "hubspot": {
        "required": [
            "HubSpot_Deal_ID", "Fiscal_Period", "Company_Name", "Product",
            "Deal_Stage", "Stage_Probability", "Amount",
            "Billing_Frequency", "Expected_Close_Date", "AE_Owner",
        ],
        "numeric": ["Stage_Probability", "Amount"],
        "dates": {"Expected_Close_Date": "%Y-%m-%d"},
    },
    "scorecard": {
        "required": [
            "Rank", "Opportunity_ID_15", "Hospital_Shorthand_Name",
            "Product", "Sales_Rep", "Leadership_Score",
            "Commercial_Score", "Contractual_Score", "Composite_GPA",
            "Win_Probability", "VP_Notes",
        ],
        "numeric": [
            "Rank", "Leadership_Score", "Commercial_Score",
            "Contractual_Score", "Composite_GPA", "Win_Probability",
        ],
        "dates": {},
    },
    "probability_rules": {
        "required": [
            "GPA Tier", "Min_GPA_Inclusive",
            "Max_GPA_Exclusive", "Win_Probability",
        ],
        "numeric": [
            "Min_GPA_Inclusive", "Max_GPA_Exclusive", "Win_Probability",
        ],
        "dates": {},
    },
}

