# PulseFlow Health Forecast

Local executive dashboard built with React, Tailwind CSS, and FastAPI. A repeatable
Python pipeline cleans four exports, prepares the baseline forecast, and records
data-quality findings. Scenario changes are temporary and do not modify source data.

## Run locally

Prerequisites: Python with pip and Node.js with npm. Run these commands from the
repository root (PowerShell shown):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run_ingestion.py
python -m uvicorn api.main:app --reload
```

In a second terminal, from the repository root:

```powershell
cd frontend
npm ci
npm run dev
```

Open the frontend URL printed by Vite. API documentation is available at
http://127.0.0.1:8000/docs. Optional command-line checks:

```powershell
python forecast.py
python movements.py
```

## Process a new week's drop

1. Archive the previous inputs outside `data/raw/`, then place the new exports
   there using the same filenames below. The prior-week Salesforce file should
   contain the preceding snapshot.
2. Run `python run_ingestion.py`. Review the audit and any failure details before
   using the outputs. Ambiguous records need an explicit decision in
   `pipeline/overrides.py`; do not edit the raw files to fix them.
3. Reload the dashboard to load the new successful run and reset old scenarios.

The exercise uses **October 15, 2026** as its reference date and **Q4-2026** as the
target period. These settings live in `pipeline/config.py`; retain them for this
exercise. Review them deliberately when adapting the app to another quarter.

Each attempt writes to `outputs/runs/<run_id>/`. The API uses
`outputs/latest_successful_run.json`; a failed attempt does not replace the last
successful dataset. Check `outputs/latest_run.json` for the newest attempt's
status. Failure folders contain an error traceback and available audit findings.

## Data anomalies and treatment

Source key:

| Key | File in `data/raw/` |
| --- | --- |
| Current SF | `1_sfdc_pipeline_current.csv` |
| Prior SF | `2_sfdc_pipeline_prior_week.csv` |
| VP | `3_vp_deal_scorecard.xlsx` |
| HubSpot | `4_carebridge_hubspot_export.csv` |

The table includes data errors, source-format differences, and business conflicts.
Not every difference is an error that should be overwritten. IDs below sometimes
use their distinctive suffix for readability.

| Anomaly / discrepancy | Source(s) | Treatment and reasoning |
| --- | --- | --- |
| Empty export padding | Current SF; Prior SF | Remove only fully empty rows and unnamed, fully empty columns. Removed 163 current rows, 170 prior rows, and 7 columns from each export. Preserve source row numbers before removal. |
| Exact duplicate: Cascadia `L014` | Current SF | Compare business fields. Keep one identical record and log the removed copy. |
| Exact duplicate: `HS-9002` | HubSpot | Keep one identical record and log the removed copy. |
| Conflicting Caledonia `L008` versions | Current SF, compared with Prior SF | **Assumption:** select $550K / Contract Negotiations / 80% / 2 days in stage. The other current version repeats the prior $400K / Business Approval state. This suggests an update but no timestamp proves precedence; selection is an explicit override. |
| Mixed 15- and 18-character Salesforce IDs | Current SF; Prior SF; VP | Preserve original IDs and add case-preserving first-15-character matching keys. Six prior IDs are shorter than their current counterparts; normalization prevents false new-deal classifications. |
| Four missing scorecard IDs | VP, reconciled to Current SF | Explicitly map Ironwood, Borealis, Starlight, and Halcyon to `T005`–`T008`. Record the mapping reason, preserve original blanks, and validate unique matches plus product and rep agreement. |
| Customer shorthand, aliases, and Borealis campus ambiguity | VP; Current SF | Prefer IDs and documented mappings over broad name matching. Borealis maps to Main Campus `T006`, supported by Clara Oswald and the VP note. North Surgery Clinic `L020` stays separate. |
| Different stage vocabularies | Current SF; Prior SF; HubSpot | Define equivalent stages: Technical Validation / Qualified to Buy (40%), Business Approval / Decision Maker Bought-In (60%), and Contract Negotiations / Contract Sent (80%). Preserve original stage labels. |
| Monthly and annual amounts share an `Amount` column | HubSpot, combined with Salesforce | Add `Annual_ACV`: monthly amount × 12; annual amount unchanged. Preserve raw amount and frequency; flag unsupported frequencies rather than assuming annual. |
| Same apparent Aethelgard CareBridge deal in both CRMs | Current SF `M001`; HubSpot `HS-9001` | **Assumption:** treat as one deal because customer, product, owner, close date, equivalent stage, and $180K annual value agree. Retain Salesforce for combined inclusion; keep HubSpot's row with an exclusion flag. The Salesforce record still counts as new to that snapshot. |
| Different date representations | Current SF; Prior SF; HubSpot | Parse Salesforce `M/D/YYYY` and HubSpot `YYYY-MM-DD` explicitly. Export dates consistently; report parsing failures. |
| Scorecard GPA and probabilities are stored values | VP | Independently calculate weighted GPA and the prescribed probability rather than trusting stored results. All eight stored GPAs agree with the scores. |
| Ironwood's 75% manual probability override | VP | Scores 4/2/2 yield GPA 2.40 and a **50% baseline**. Preserve exported 75% and the explanatory VP note; log the disagreement. |
| Closed Lost with nonzero probability | Current SF Coral Reef `X005`; HubSpot Celestial `HS-9013` | Flag the exported 40% and 30% values. Exclude Closed Lost records based on status, regardless of probability. |
| Past expected close dates on open deals | Current SF Hyperion `L001`, Obsidian `L002`, Valkyrie `L003`; HubSpot Zephyr `HS-9004` | **Business review: 4 warnings.** Flag stale dates relative to October 15, 2026. Keep otherwise eligible Q4 deals: a past date alone does not establish a lost deal. |
| Stage age appears not to reset after a stage change | Current SF compared with Prior SF: `L009`, `L010`, `T002`, `T004`, `T006` | **Business review: 5 warnings.** All five durations increased by seven despite a changed stage. Preserve the values pending clarification of the metric; stage age does not affect forecast math. |
| CRM source differs from product classification | Current SF retained CareBridge `M001`; HubSpot | The dashboard groups longtail by source and labels the acquired subtotal **CareBridge (HubSpot)**. Salesforce's subtotal includes $144K expected value from its CareBridge deal; this prevents presenting the HubSpot subtotal as the complete product total. |

Source files remain unchanged. Prepared records carry source locations, and audit
events document findings and decisions. Audit counts are **events, not unique
problems**: detection and resolution can be separate entries. Successful
annualization and date normalization are reflected in prepared fields rather than
necessarily generating an individual audit event for every record.

### How review warnings work

Amber exclamation icons identify business-review warnings in the sidebar and
audit table. The supplied data has **9 warnings**: four stale close dates and five
stage-age inconsistencies. Expand an audit event to inspect its source location,
original value, and recorded treatment.

Review is informational in this MVP: there is no assignment, approval, or saved
acknowledgement workflow.
