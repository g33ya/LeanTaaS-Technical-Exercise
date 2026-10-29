"""Clean individual tables without cross-system matching."""
import pandas as pd

from .config import SOURCE_COLUMNS


def check_duplicates(df, id_column):
    df = df.copy()
    issues = []

    # Source locations differ even when the business records are identical.
    business_columns = [
        column for column in df.columns
        if column not in SOURCE_COLUMNS
    ]

    def log_issue(row, issue, **details):
        issues.append({
            "source_file": row["source_file"],
            "source_sheet": row.get("source_sheet", None),
            "source_row": int(row["source_row"]),
            "column": id_column,
            "raw_value": row[id_column],
            "issue": issue,
            **details,
        })

    # Only deduplicate records that have an ID.
    has_id = (
        df[id_column].notna()
        & df[id_column].astype("string").str.strip().ne("").fillna(False)
    )

    exact_duplicates = pd.Series(False, index=df.index)
    exact_duplicates.loc[has_id] = df.loc[has_id].duplicated(
        subset=business_columns,
        keep="first",
    )

    for _, row in df.loc[exact_duplicates].iterrows():
        log_issue(
            row,
            "Exact duplicate removed; first occurrence retained",
        )

    df = df.loc[~exact_duplicates].copy()

    # After exact duplicates are removed, repeated IDs indicate conflicts.
    has_id = (
        df[id_column].notna()
        & df[id_column].astype("string").str.strip().ne("").fillna(False)
    )

    conflicting = (
        has_id
        & df[id_column].duplicated(keep=False)
    )

    for _, group in df.loc[conflicting].groupby(id_column, sort=False):
        differing_columns = [
            column for column in business_columns
            if group[column].nunique(dropna=False) > 1
        ]

        for _, row in group.iterrows():
            log_issue(
                row,
                "Conflicting duplicate ID; retained for review",
                differing_columns=", ".join(differing_columns),
            )

    return df.reset_index(drop=True), issues


def add_salesforce_match_key(df, id_column, allowed_lengths):
    df = df.copy()
    issues = []

    ids = df[id_column].astype("string")

    present = ids.notna() & ids.str.strip().ne("").fillna(False)
    valid = (
        present
        & ids.str.len().isin(allowed_lengths)
        & ids.str.fullmatch(r"[A-Za-z0-9]+", na=False)
    )

    # Preserve case. Missing or malformed IDs receive no matching key.
    df["sf_match_key"] = ids.str.slice(0, 15).where(valid, pd.NA)

    for index in df.index[present & ~valid]:
        issues.append({
            "source_file": df.at[index, "source_file"],
            "source_sheet": (
                df.at[index, "source_sheet"]
                if "source_sheet" in df.columns else None
            ),
            "source_row": int(df.at[index, "source_row"]),
            "column": id_column,
            "raw_value": ids.at[index],
            "issue": (
                "Invalid Salesforce ID format; expected an alphanumeric "
                f"ID of length {sorted(allowed_lengths)}"
            ),
        })

    return df, issues


def annualize_amounts(df):
    df = df.copy()
    issues = []

    # Normalize only for comparison; preserve the original frequency column.
    frequency = (
        df["Billing_Frequency"]
        .astype("string")
        .str.strip()
        .str.casefold()
    )

    multiplier = frequency.map({"annual": 1, "monthly": 12})
    amount = pd.to_numeric(df["Amount"], errors="coerce")

    valid_amount = amount.notna() & amount.ge(0) & amount.lt(float("inf"))

    df["Annual_ACV"] = (amount * multiplier).where(
        valid_amount & multiplier.notna()
    )

    for index in df.index:
        problems = []

        if pd.isna(multiplier.at[index]):
            problems.append("Missing or unsupported billing frequency")

        if not valid_amount.at[index]:
            problems.append("Missing, invalid, negative, or infinite amount")

        if problems:
            issues.append({
                "source_file": df.at[index, "source_file"],
                "source_sheet": (
                    df.at[index, "source_sheet"]
                    if "source_sheet" in df.columns else None
                ),
                "source_row": int(df.at[index, "source_row"]),
                "column": "Annual_ACV",
                "raw_value": (
                    f"Amount={df.at[index, 'Amount']}; "
                    f"Billing_Frequency={df.at[index, 'Billing_Frequency']}"
                ),
                "issue": "; ".join(problems),
                "resolution": "Annual_ACV left missing; requires review",
            })

    return df, issues
