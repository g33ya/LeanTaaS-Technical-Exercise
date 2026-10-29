"""Read source exports and preserve provenance."""
from pathlib import Path

import pandas as pd

from .config import RAW_DATA_DIR


def load_csv(file_path):
    file_path = Path(file_path)
    if not file_path.is_absolute():
        file_path = RAW_DATA_DIR / file_path

    # Keep identifiers and other raw values as strings.
    df = pd.read_csv(
        file_path,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8-sig",
        skip_blank_lines=False,
    )

    # Treat whitespace-only cells as empty when checking export padding.
    empty_cells = df.apply(lambda column: column.str.strip().eq(""))

    empty_rows = empty_cells.all(axis=1)
    empty_columns = [
        column
        for column in df.columns
        if column.startswith("Unnamed:") and empty_cells[column].all()
    ]

    issues = [
        {
            "source_file": file_path.name,
            "issue": "Empty export padding removed",
            "rows_removed": int(empty_rows.sum()),
            "columns_removed": len(empty_columns),
        }
    ]

    # Header is row 1, so the first data record is row 2.
    df.insert(0, "source_row", range(2, len(df) + 2))
    df.insert(0, "source_file", file_path.name)

    df = df.loc[~empty_rows].drop(columns=empty_columns).copy()
    df = df.reset_index(drop=True)

    return df, issues


def load_scorecard(file_path):
    file_path = Path(file_path)
    if not file_path.is_absolute():
        file_path = RAW_DATA_DIR / file_path

    df = pd.read_excel(
        file_path,
        sheet_name="Top 8 Scorecard",
        header=3,  # Zero-based: Excel row 4 contains the headers.
        dtype="string",
        keep_default_na=False,
        engine="openpyxl",
    )

    empty_cells = df.apply(lambda column: column.str.strip().eq(""))
    empty_rows = empty_cells.all(axis=1)

    empty_columns = [
        column
        for column in df.columns
        if column.startswith("Unnamed:") and empty_cells[column].all()
    ]

    issues = [
        {
            "source_file": file_path.name,
            "source_sheet": "Top 8 Scorecard",
            "issue": "Empty export padding removed",
            "rows_removed": int(empty_rows.sum()),
            "columns_removed": len(empty_columns),
        }
    ]

    # The first data record is on Excel row 5.
    df.insert(0, "source_row", range(5, len(df) + 5))
    df.insert(0, "source_sheet", "Top 8 Scorecard")
    df.insert(0, "source_file", file_path.name)

    df = df.loc[~empty_rows].drop(columns=empty_columns).copy()
    df = df.reset_index(drop=True)

    return df, issues


def load_probability_rules(file_path):
    """Load the reference sheet whose headers occupy Excel row 3."""
    file_path = Path(file_path)
    if not file_path.is_absolute():
        file_path = RAW_DATA_DIR / file_path
    df = pd.read_excel(
        file_path,
        sheet_name="GPA Probability Rules",
        header=2,
        dtype="string",
        keep_default_na=False,
        engine="openpyxl",
    )
    df.insert(0, "source_row", range(4, len(df) + 4))
    df.insert(0, "source_sheet", "GPA Probability Rules")
    df.insert(0, "source_file", file_path.name)
    return df, []
