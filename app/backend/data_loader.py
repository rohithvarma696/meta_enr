import os
import logging
import pandas as pd
from datetime import datetime

from config import CONTENTS_ROOT, TODAY

logger = logging.getLogger(__name__)


def get_projects() -> list[str]:
    """Return all project-ID folders inside the contents root."""
    if not os.path.isdir(CONTENTS_ROOT):
        return []
    return sorted(
        d for d in os.listdir(CONTENTS_ROOT)
        if os.path.isdir(os.path.join(CONTENTS_ROOT, d))
    )


def _find_csv(project_id: str, date: str) -> str | None:
    """Build the CSV path for a given project + date folder."""
    folder = os.path.join(CONTENTS_ROOT, project_id, date)
    if not os.path.isdir(folder):
        return None
    for fname in os.listdir(folder):
        if fname.endswith(".csv"):
            return os.path.join(folder, fname)
    return None


def load_contents(project_id: str, date: str) -> pd.DataFrame:
    """Load the contents CSV for a project + date. Raises if not found."""
    csv_path = _find_csv(project_id, date)
    if not csv_path:
        raise FileNotFoundError(
            f"No CSV found for project={project_id}, date={date}"
        )
    logger.info("Loading CSV: %s", csv_path)
    df = pd.read_csv(csv_path, low_memory=False, sep='\t')

    # Ensure the columns we need exist (fill with empty string if missing)
    for col in ["contenttype", "created_on", "modified_on", "partnername",
                "contentid", "contentname", "director", "cast", "imgurl",
                "enriched_meta_status"]:
        if col not in df.columns:
            df[col] = ""

    # Normalise date columns to plain date strings (YYYY-MM-DD)
    for col in ("created_on", "modified_on"):
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")

    return df


def get_available_dates(project_id: str) -> list[str]:
    """Scan date folders for a project and return them newest-first."""
    project_dir = os.path.join(CONTENTS_ROOT, project_id)
    if not os.path.isdir(project_dir):
        return []
    folders = sorted(
        d for d in os.listdir(project_dir)
        if os.path.isdir(os.path.join(project_dir, d)) and d.isdigit()
    )
    return list(reversed(folders))  # newest first


def get_content_types(df: pd.DataFrame) -> list[str]:
    """Unique content types from a loaded DataFrame."""
    return sorted(df["contenttype"].dropna().unique().tolist())


def get_dates_for_type(df: pd.DataFrame, content_type: str) -> list[str]:
    """Unique dates (created_on OR modified_on) after filtering by content type."""
    filtered = df[df["contenttype"] == content_type] if content_type else df
    dates_created  = filtered["created_on"].dropna()
    dates_modified = filtered["modified_on"].dropna()
    all_dates = pd.concat([dates_created, dates_modified]).unique().tolist()
    # Remove NaT-stringified values
    return sorted([d for d in all_dates if d and d != "NaT"], reverse=True)


def get_partners(
    df: pd.DataFrame,
    content_type: str,
    date: str,
) -> list[str]:
    """Partner names after applying contenttype + date filter."""
    filtered = df.copy()
    if content_type:
        filtered = filtered[filtered["contenttype"] == content_type]
    if date:
        date_mask = (
            filtered["created_on"].fillna("").str.contains(date, regex=False)
            | filtered["modified_on"].fillna("").str.contains(date, regex=False)
        )
        filtered = filtered[date_mask]
    return sorted(filtered["partnername"].dropna().unique().tolist())


def get_enriched_meta_statuses(
    df: pd.DataFrame,
    content_type: str,
    date: str,
    partners: list[str],
) -> list[str]:
    """Unique enriched_meta_status values after applying upstream filters."""
    filtered = df.copy()
    if content_type:
        filtered = filtered[filtered["contenttype"] == content_type]
    if date:
        date_mask = (
            filtered["created_on"].fillna("").str.contains(date, regex=False)
            | filtered["modified_on"].fillna("").str.contains(date, regex=False)
        )
        filtered = filtered[date_mask]
    if partners:
        filtered = filtered[filtered["partnername"].isin(partners)]
    vals = (
        filtered["enriched_meta_status"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )
    return sorted(v for v in vals if v and v.lower() not in ("", "nan"))


def filter_contents(
    df: pd.DataFrame,
    content_type: str,
    date: str,
    partners: list[str],
    enriched_meta_status: str = "",
) -> pd.DataFrame:
    """
    Apply cascade filters in order:
      1. contenttype
      2. created_on OR modified_on date
      3. partnername (multi-select — skip if empty list)
      4. enriched_meta_status (skip if empty)
    """
    filtered = df.copy()

    if content_type:
        filtered = filtered[filtered["contenttype"] == content_type]

    if date:
        date_mask = (
            filtered["created_on"].fillna("").str.contains(date, regex=False)
            | filtered["modified_on"].fillna("").str.contains(date, regex=False)
        )
        filtered = filtered[date_mask]

    if partners:
        filtered = filtered[filtered["partnername"].isin(partners)]

    if enriched_meta_status:
        filtered = filtered[
            filtered["enriched_meta_status"].astype(str) == enriched_meta_status
        ]

    return filtered.reset_index(drop=True)
