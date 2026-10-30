"""Pipeline orchestration: follow main() to see each cleaning stage in order."""
from pathlib import Path

from pipeline.audit import build_audit_log
from pipeline.cleaning import (
    add_salesforce_match_key, annualize_amounts, check_duplicates,
)
from pipeline.config import OUTPUT_ROOT
from pipeline.loaders import load_csv, load_probability_rules, load_scorecard
from pipeline.overrides import (
    CONFLICT_OVERRIDES, CROSS_SYSTEM_MAPPINGS, SCORECARD_ID_OVERRIDES,
)
from pipeline.reconciliation import (
    match_scorecard, reconcile_cross_system, refresh_scorecard_salesforce,
    resolve_conflicts,
)
from pipeline.validation import (
    check_cleaning_readiness, mark_forecast_eligibility,
    validate_categories_and_keys, validate_scorecard_probabilities,
    validate_stage_probabilities, validate_stage_aging, validate_table,
)

# The runner reads completed audit events if a stage fails.
all_issues = []


def main(output_dir=None):
    """Load, clean, reconcile, validate, and export one data drop."""
    global all_issues
    all_issues = []

    # 1. Load raw sources.
    current, current_issues = load_csv('1_sfdc_pipeline_current.csv')
    prior, prior_issues = load_csv('2_sfdc_pipeline_prior_week.csv')
    hubspot, hubspot_issues = load_csv('4_carebridge_hubspot_export.csv')
    scorecard, scorecard_issues = load_scorecard('3_vp_deal_scorecard.xlsx')
    probability_rules, probability_rules_issues = load_probability_rules(
        '3_vp_deal_scorecard.xlsx',
    )
    all_issues = (
        current_issues
        + prior_issues
        + hubspot_issues
        + scorecard_issues
        + probability_rules_issues
    )

    # 2. Validate schemas and field types.
    current_clean, current_validation = validate_table(current, 'salesforce')
    prior_clean, prior_validation = validate_table(prior, 'salesforce')
    hubspot_clean, hubspot_validation = validate_table(hubspot, 'hubspot')
    scorecard_clean, scorecard_validation = validate_table(scorecard, 'scorecard')
    rules_clean, rules_validation = validate_table(probability_rules, 'probability_rules')
    validation_issues = (
        current_validation
        + prior_validation
        + hubspot_validation
        + scorecard_validation
        + rules_validation
    )
    all_issues += validation_issues

    # 3. Remove exact duplicates; retain conflicting versions.
    current_clean, current_duplicate_issues = check_duplicates(current_clean, 'Opportunity_ID')
    prior_clean, prior_duplicate_issues = check_duplicates(prior_clean, 'Opportunity_ID')
    hubspot_clean, hubspot_duplicate_issues = check_duplicates(hubspot_clean, 'HubSpot_Deal_ID')
    scorecard_clean, scorecard_duplicate_issues = check_duplicates(
        scorecard_clean,
        'Opportunity_ID_15',
    )
    duplicate_issues = (
        current_duplicate_issues
        + prior_duplicate_issues
        + hubspot_duplicate_issues
        + scorecard_duplicate_issues
    )
    all_issues += duplicate_issues

    # 4. Normalize Salesforce matching keys.
    current_clean, current_id_issues = add_salesforce_match_key(
        current_clean,
        'Opportunity_ID',
        allowed_lengths={15, 18},
    )
    prior_clean, prior_id_issues = add_salesforce_match_key(
        prior_clean,
        'Opportunity_ID',
        allowed_lengths={15, 18},
    )
    scorecard_clean, scorecard_id_issues = add_salesforce_match_key(
        scorecard_clean,
        'Opportunity_ID_15',
        allowed_lengths={15},
    )
    id_issues = current_id_issues + prior_id_issues + scorecard_id_issues
    all_issues += id_issues

    # 5. Apply documented conflict and scorecard identity decisions.
    current_resolved, resolution_issues = resolve_conflicts(current_clean, CONFLICT_OVERRIDES)
    all_issues += resolution_issues
    scorecard_matched, scorecard_match_issues = match_scorecard(
        scorecard_clean,
        current_resolved,
        SCORECARD_ID_OVERRIDES,
    )
    all_issues += scorecard_match_issues

    # 6. Annualize amounts and reconcile shared deals.
    current_resolved, current_acv_issues = annualize_amounts(current_resolved)
    prior_clean, prior_acv_issues = annualize_amounts(prior_clean)
    hubspot_clean, hubspot_acv_issues = annualize_amounts(hubspot_clean)
    acv_issues = current_acv_issues + prior_acv_issues + hubspot_acv_issues
    all_issues += acv_issues
    current_reconciled, hubspot_reconciled, reconciliation_issues = reconcile_cross_system(
        current_resolved,
        hubspot_clean,
        CROSS_SYSTEM_MAPPINGS,
    )
    all_issues += reconciliation_issues

    # 7. Check eligibility, dates, and probabilities.
    current_eligible, current_eligibility_issues = mark_forecast_eligibility(
        current_reconciled,
        'salesforce',
    )
    hubspot_eligible, hubspot_eligibility_issues = mark_forecast_eligibility(
        hubspot_reconciled,
        'hubspot',
    )
    eligibility_issues = current_eligibility_issues + hubspot_eligibility_issues
    all_issues += eligibility_issues
    current_checked, current_probability_issues = validate_stage_probabilities(
        current_eligible,
        'salesforce',
    )
    prior_checked, prior_probability_issues = validate_stage_probabilities(
        prior_clean,
        'salesforce',
    )
    hubspot_checked, hubspot_probability_issues = validate_stage_probabilities(
        hubspot_eligible,
        'hubspot',
    )
    scorecard_checked, scorecard_probability_issues = validate_scorecard_probabilities(
        scorecard_matched,
    )
    probability_issues = (
        current_probability_issues
        + prior_probability_issues
        + hubspot_probability_issues
        + scorecard_probability_issues
    )
    all_issues += probability_issues

    # 8. Validate final categories, keys, and strategic matches.
    category_key_issues = (
        validate_categories_and_keys(current_checked, 'salesforce')
        + validate_categories_and_keys(prior_checked, 'salesforce')
        + validate_categories_and_keys(hubspot_checked, 'hubspot')
    )
    all_issues += category_key_issues
    if category_key_issues:
        raise ValueError('Category or key validation failed. Review the issues above.')
    all_issues += validate_stage_aging(current_checked, prior_checked)
    scorecard_ready = refresh_scorecard_salesforce(scorecard_checked, current_checked)
    check_cleaning_readiness(current_checked, prior_checked, hubspot_checked, scorecard_ready)

    # 9. Consolidate audit events and block unresolved findings.
    audit_log = build_audit_log(all_issues, current_checked, hubspot_checked)
    unresolved = audit_log.loc[audit_log['status'].eq('requires_review')]
    if not unresolved.empty:
        raise ValueError('Unresolved audit findings remain. Review them before saving outputs.')

    # 10. Export the prepared tables.
    output_dir = Path(output_dir) if output_dir is not None else OUTPUT_ROOT
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared_tables = {
        'salesforce_current_clean.csv': current_checked,
        'salesforce_prior_clean.csv': prior_checked,
        'hubspot_clean.csv': hubspot_checked,
        'strategic_scorecard_clean.csv': scorecard_ready,
        'probability_rules_clean.csv': rules_clean,
        'audit_log.csv': audit_log,
    }
    for filename, table in prepared_tables.items():
        table.to_csv(
            output_dir / filename,
            index=False,
            encoding='utf-8-sig',
            date_format='%Y-%m-%d',
        )
    print(f"Cleaning complete: {len(prepared_tables)} files saved to {output_dir}")


if __name__ == "__main__":
    main()
