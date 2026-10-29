# PulseFlow Health — Associate GTM Engineer Technical Exercise

**Role:** Associate GTM Engineer (L3)  
**Time Budget:** ~3–4 hours (AI coding tools such as Claude Code, OpenCode, Cursor, Copilot, or Antigravity are **strongly encouraged**)  
**As-Of Reference Date:** Use **`2026-10-15`** as "today's date" for all date comparisons.  
**Deliverables:**
1. **A Working Web Application** (runs locally or hosted via URL)
2. **A Repeatable Data Processing Script / Pipeline** (Python, Node/TypeScript, or SQL) that ingests the 4 raw files below
3. **A Brief `README.md`** explaining how to run your pipeline against a new week's data drop and what data bugs you caught

---

## 1. The Scenario (No Prior Sales or Finance Knowledge Required!)

Welcome to **PulseFlow Health**. We sell operational software subscriptions to hospital systems across three core product lines (`PulseOR`, `BedFlow`, and `InfusionIQ`), and we recently acquired a smaller startup that sells a post-acute care product (`CareBridge`).

Every **Monday at 12:00 PM**, our CEO, Chief Revenue Officer (CRO), and Chief Financial Officer (CFO) meet to answer one question:
> **"How much new annual software sales will we close in Q4-2026, and are we going to hit our $12,000,000 Q4 Board Target?"**

Right now, preparing for this meeting is a painful **3-hour manual spreadsheet fire drill**. Every Monday morning, someone on our team downloads **4 disconnected files** from different systems and manually copies, pastes, cleans, and cross-checks them in Excel. Worse, because the data comes from multiple systems (including our newly acquired startup), raw exports contain dirty data that can make the executive numbers wrong if someone isn't careful.

**Your Mission:** Replace that 3-hour manual Excel process with **a repeatable data script + an interactive web dashboard** that our executives can use live during the Monday forecast meeting.

> ⚠️ **Important Note on Data Quality & AI Tooling:**  
> Just like real-world RevOps exports, **the data across these 4 files is messy and inconsistent.** While we strongly encourage you to build fast with AI coding tools (Claude Code, OpenCode, Cursor, Copilot, etc.), **do not blindly trust a one-shot AI prompt to get the math right.** You will need to actively inspect the raw data, exercise real diligence to catch cross-file discrepancies and edge cases, and make sure you can defend the accuracy of your final numbers.

---

## 2. Plain-English Business Glossary & Deterministic Math Rules

You do **not** need a finance or sales background for this exercise. Everything you need to know is defined in the 4 rules below:

### Rule 1: Monthly Value (`MRR`) vs. Annual Value (`ACV`)
*   **What it means:** We sell software subscriptions to hospitals. Our executives measure everything in **Annual Contract Value (`ACV`)** — how much a contract is worth **over 12 months (1 full year)**.
*   **How it appears in your files:**
    *   In our main **Salesforce export (`1_sfdc_pipeline_current.csv`)**, the deal amount is **already annual (`ACV`)** (`Billing_Frequency == "Annual"`).
    *   However, our newly acquired startup (**CareBridge**, exported from **HubSpot** in `4_carebridge_hubspot_export.csv`) has a `Billing_Frequency` column that says either `"Monthly"` (meaning the dollar amount shown is only **1 month** of fees, often called `MRR`) or `"Annual"` (12 months of fees).
*   **Your Code Rule:** Before combining or summing any deals, convert every deal into **Annual Contract Value (`Annual_ACV`)**:
    *   If `Billing_Frequency == "Monthly"` → `Annual_ACV = Amount * 12`
    *   If `Billing_Frequency == "Annual"` → `Annual_ACV = Amount`

---

### Rule 2: How Our Forecast Splits Deals Into Two Buckets ("Top 8 Strategic Deals" vs. "The Longtail")
In enterprise hospital sales, a few huge multi-million-dollar deals can swing the whole quarter, while dozens of smaller deals behave like a steady average. Therefore, our forecast splits all active **Q4-2026** deals into two buckets:

#### Bucket A: The "Top 8 Strategic Deals" (Listed in `3_vp_deal_scorecard.xlsx`)
*   Our Sales VPs hand-pick up to **8 major deals** to debate live on the Monday call.
*   In the Excel file (`3_vp_deal_scorecard.xlsx`), the VPs score each of these 8 deals on a **1 to 4 scale** across three criteria:
    1. **Leadership Alignment** (Weight: **20%**) — *Do the hospital executives support the project?*
    2. **Commercial Alignment** (Weight: **20%**) — *Do they agree with the price and ROI?*
    3. **Contractual Alignment** (Weight: **60%**) — *Are the legal contracts redlined and close to signature?*
*   **How to calculate a Top 8 Deal's Expected Value:**
    1. Calculate the weighted **Composite Score (`GPA`)**:
       ```text
       Composite GPA = ROUND((0.20 × Leadership) + (0.20 × Commercial) + (0.60 × Contractual), 2)
       ```
    2. Convert that `Composite GPA` into a **Win Probability %** using this exact lookup table:
       *   `GPA >= 3.20` → **75% chance to close** (`0.75`)
       *   `GPA >= 2.40 and < 3.20` → **50% chance to close** (`0.50`)
       *   `GPA >= 1.60 and < 2.40` → **30% chance to close** (`0.30`)
       *   `GPA < 1.60` → **10% chance to close** (`0.10`)
    3. Multiply the deal's Annual Value (from `1_sfdc_pipeline_current.csv`) by its GPA Win Probability:
       ```text
       Expected Value (Top 8 Deal) = Annual ACV × Win Probability
       ```

#### Bucket B: The "Forecasted Longtail" (All Other Active Q4-2026 Deals)
*   **"Longtail"** simply means **all other active Q4-2026 deals** across both our main Salesforce pipeline (`1_sfdc_pipeline_current.csv`) and our acquired CareBridge HubSpot pipeline (`4_carebridge_hubspot_export.csv`) that are **NOT** already in the Top 8 Strategic Deals list.
*   Because executives don't review these smaller deals one by one, each Longtail deal uses the `Stage_Probability` percentage (`0.0` to `1.0`) provided in the CSV:
    ```text
    Expected Value (Longtail Deal) = Annual ACV × Stage Probability
    ```

#### The Master Quarterly Forecast Formula

```text
Total Expected Q4 Sales  = SUM(Expected Value of Top 8 Deals) + SUM(Expected Value of All Longtail Deals)
Variance to Board Target = Total Expected Q4 Sales − $12,000,000
```

---

### Rule 3: Week-over-Week Salesforce Pipeline Changes (`1_sfdc_pipeline_current.csv` vs. `2_sfdc_pipeline_prior_week.csv`)
Executives always ask: *"What changed in our Salesforce pipeline since last Monday?"* By comparing the Current Week file against the Prior Week file, your app should break out:
1. **New Deals Added:** Deals present in Current Week that were not in Prior Week.
2. **Slipped Deals (Out of Q4):** Deals that were in `Q4-2026` in Prior Week, but moved to `Q1-2027` in Current Week.
3. **Closed Lost Deals:** Deals that were open in Prior Week, but moved to `Closed Lost` in Current Week.
4. **Stage Moves (on Active Q4-2026 Deals):** Active Q4 deals whose `Stage` advanced or regressed since Prior Week. Our ordered Salesforce stages from earliest to latest are:
   *   `Introduction` (`0.20`) → `Technical Validation` (`0.40`) → `Business Approval` (`0.60`) → `Contract Negotiations` (`0.80`)
5. **ACV Amount Changes (on Active Q4-2026 Deals):** Active Q4 deals whose `Amount` increased (expansion) or decreased (contraction) since Prior Week.

---

### Rule 4: Don't Trust Raw Exports (Data Diligence & Audit Log)
Because these 4 files are raw exports pulled from different systems (Salesforce, HubSpot, and a manual VP Excel tracker), **nobody has reconciled them against each other. It's your job to find out what's wrong with them.**
*   **Do not clean the files by hand in Excel, and do not assume a naive join/sum is accurate.** Your ingestion script must handle every fix programmatically—and where you find genuine business conflicts or judgment calls, surface them clearly (or give the executive a toggle) rather than hiding them.
*   Include a **"Data Hygiene & Audit Log"** tab in your web app that documents every issue your pipeline caught and how it was resolved, so the CFO can trust your numbers.

---

## 3. What Your Web App Should Include

You have full creative freedom on the tech stack and design (React, Next.js, FastAPI, Flask, Vue, Tailwind, ECharts/Recharts/Chart.js, etc.), as long as it is clean, fast, and intuitive for a non-technical executive:

1. **Top KPI Summary Banner:**
   *   Shows **Total Expected Q4 Sales**, **Top 8 Strategic Deals Expected Value**, **Forecasted Longtail Expected Value** (broken out by Core Salesforce vs. Acquired CareBridge), and **Variance vs. the $12.0M Board Target**.
2. **Interactive "What-If" Deal Room (Top 8 + Longtail Table):**
   *   Allows the user to adjust a Top 8 deal's `Leadership / Commercial / Contractual` scores (1–4) or promote/demote a deal between the Top 8 and the Longtail pool (if promoting a Longtail deal into the Top 8, default its initial scores to `Leadership=3, Commercial=3, Contractual=3` → `GPA 3.00 / 50%`), and **recalculates the top KPI banner and charts immediately** with a "Reset to Baseline" button.
   *   Allows filtering by Product Line (`PulseOR`, `BedFlow`, `InfusionIQ`, `CareBridge`) or Sales Rep.
3. **Week-over-Week Salesforce Movement View:**
   *   A clear visual or table showing the 5 movement categories between Prior Week and Current Week (New Deals, Slipped to Q1-2027, Closed Lost, Stage Moves, and ACV Changes).
4. **Data Hygiene & Audit Log Tab:**
   *   Displays a clear audit table of every data quality issue your ingestion pipeline detected (and how it was resolved) across the 4 source files.

---

## 4. How We Will Review It Together (20-Minute Live Debrief)

In our follow-up call, you will share your screen and walk us through:
1. **A 5-minute demo** of your app as if we were the CRO and CFO on Monday morning.
2. **How your ingestion pipeline works under the hood** (and which data traps it caught).
3. **A live curveball:** We will hand you a new file (`week_2_update.csv`) or ask for a small live tweak so you can show us how you run your pipeline and iterate using your AI coding workflow.
