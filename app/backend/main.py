import logging
import math
import os
import re
import csv
from datetime import datetime
from typing import Optional

import requests as http_requests

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import data_loader as dl
import faiss_engine as fe

# ── logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── app ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Meta Enrichment API", version="1.0.0")

# Allow the React dev server (port 5173) and any other origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── in-memory state ──────────────────────────────────────────────────────────
# We keep the loaded DataFrame in memory so filter sub-endpoints are fast
_loaded: dict = {}   # { "project_id": str, "load_date": str, "df": pd.DataFrame }


def _get_df(project_id: str):
    """Return cached DataFrame for the latest folder or load it fresh."""
    # Find the latest daily load folder
    dates = dl.get_available_dates(project_id)
    if not dates:
        raise FileNotFoundError(f"No date folders found for project: {project_id}")
    load_date = dates[0]  # Take newest, e.g., '20260213'

    if (
        _loaded.get("project_id") != project_id
        or _loaded.get("load_date") != load_date
    ):
        df = dl.load_contents(project_id, load_date)
        _loaded["project_id"] = project_id
        _loaded["load_date"]  = load_date
        _loaded["df"]         = df
    return _loaded["df"]


# ── request / response models ─────────────────────────────────────────────────

class FilterRequest(BaseModel):
    project_id:           str
    content_type:         str
    date:                 str
    partners:             list[str] = []
    enriched_meta_status: str       = ""
    page:                 int       = 1
    page_size:            int       = 50


class EnrichRequest(BaseModel):
    project_id:           str
    content_type:         str
    date:                 str
    partners:             list[str] = []
    enriched_meta_status: str       = ""
    page:                 int       = 1
    page_size:            int       = 50


class SelectMatchRequest(BaseModel):
    project_id:      str
    contentid:       str
    match:           dict
    manual_genre:    Optional[str] = None
    manual_keywords: Optional[str] = None

class SearchRequest(BaseModel):
    project_id:           str
    content_type:         str       = ""
    date:                 str       = ""
    partners:             list[str] = []
    enriched_meta_status: str       = ""
    page_size:            int       = 50
    q:                    str

class RemoveMatchRequest(BaseModel):
    project_id: str
    contentid:  str

class ManualEnrichRequest(BaseModel):
    project_id: str
    contentid:  str

class AdvancedSearchRequest(BaseModel):
    project_id: str
    contentid:  str

# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/projects", summary="List available project IDs")
def get_projects():
    projects = dl.get_projects()
    return {"projects": projects}


@app.get("/contenttypes", summary="Content types for a project")
def get_content_types(
    project_id: str = Query(...),
    date: str       = Query(default=""),
):
    try:
        # Load the latest folder's CSV to get content types
        df = _get_df(project_id)
        return {"content_types": dl.get_content_types(df)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/dates", summary="Available date folders for a project + content type")
def get_dates(
    project_id:   str = Query(...),
    content_type: str = Query(default=""),
):
    try:
        # Load the latest folder's CSV to get published dates from column
        df = _get_df(project_id)
        date_list = dl.get_dates_for_type(df, content_type)
        return {"dates": date_list}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/partners", summary="Partner names after project + type + date filter")
def get_partners(
    project_id:   str = Query(...),
    content_type: str = Query(default=""),
    date:         str = Query(default=""),
):
    try:
        df = _get_df(project_id)
        partners = dl.get_partners(df, content_type, date)
        return {"partners": partners}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/enriched_meta_statuses", summary="Unique enriched_meta_status values after upstream filters")
def get_enriched_meta_statuses(
    project_id:   str       = Query(...),
    content_type: str       = Query(default=""),
    date:         str       = Query(default=""),
    partners:     list[str] = Query(default=[]),
):
    try:
        df = _get_df(project_id)
        statuses = dl.get_enriched_meta_statuses(df, content_type, date, partners)
        return {"statuses": statuses}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/filter", summary="Apply filters and return paginated content list")
def apply_filter(req: FilterRequest):
    try:
        # Load latest daily CSV, then filter by UI criteria
        df = _get_df(req.project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    filtered = dl.filter_contents(df, req.content_type, req.date, req.partners, req.enriched_meta_status)
    total    = len(filtered)

    if total == 0:
        return {
            "count":       0,
            "page":        1,
            "page_size":   req.page_size,
            "total_pages": 0,
            "contents":    [],
        }

    total_pages = math.ceil(total / req.page_size)
    page        = max(1, min(req.page, total_pages))
    start       = (page - 1) * req.page_size
    end         = start + req.page_size

    slice_df = filtered.iloc[start:end].copy()
    slice_df = slice_df.fillna("")

    contents = []
    for _, row in slice_df.iterrows():
        contents.append({
            "contentid":   str(row.get("contentid", "")),
            "contentname": str(row.get("contentname", "")),
            "director":    str(row.get("director", "")),
            "cast":        str(row.get("cast", "")),
            "imgurl":      str(row.get("imgurl", "")),
            "contenttype": str(row.get("contenttype", "")),
            "partnername": str(row.get("partnername", "")),
            "created_on":  str(row.get("created_on", "")),
        })

    return {
        "count":       total,
        "page":        page,
        "page_size":   req.page_size,
        "total_pages": total_pages,
        "contents":    contents,
    }


@app.post("/search", summary="Search contents by id or name across all pages")
def search_contents(req: SearchRequest):
    try:
        df = _get_df(req.project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    filtered = dl.filter_contents(df, req.content_type, req.date, req.partners, req.enriched_meta_status)
    q = req.q.strip().lower()
    if not q:
        return {"results": []}

    results = []
    for idx, (_, row) in enumerate(filtered.iterrows()):
        cid   = str(row.get("contentid",   "")).lower()
        cname = str(row.get("contentname", "")).lower()
        if q in cid or q in cname:
            results.append({
                "contentid":   str(row.get("contentid",   "")),
                "contentname": str(row.get("contentname", "")),
                "page": (idx // req.page_size) + 1,
            })
        if len(results) == 5:
            break

    return {"results": results}


@app.post("/enrich", summary="Run FAISS enrichment on filtered contents")
def run_enrich(req: EnrichRequest):
    try:
        df = _get_df(req.project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    filtered = dl.filter_contents(df, req.content_type, req.date, req.partners, req.enriched_meta_status)

    if filtered.empty:
        raise HTTPException(status_code=400, detail="No contents match the selected filters.")

    # Slice for the requested page
    total = len(filtered)
    total_pages = math.ceil(total / req.page_size)
    page        = max(1, min(req.page, total_pages))
    start       = (page - 1) * req.page_size
    end         = start + req.page_size
    
    query_slice = filtered.iloc[start:end].copy()
    
    # Build the query DataFrame expected by the FAISS engine
    query_df = query_slice[["contentid", "contentname", "director", "cast", "imgurl"]].copy()
    query_df = query_df.rename(columns={"contentname": "title"})

    logger.info("Running FAISS enrichment on %d contents (page %d) …", len(query_df), page)
    results = fe.search(query_df)
    return {"total": len(results), "results": results}

@app.post("/select_match", summary="Save selected match to local CSV")
def select_match(req: SelectMatchRequest):
    try:
        df = _get_df(req.project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    content_subset = df[df["contentid"] == req.contentid]
    if content_subset.empty:
        raise HTTPException(status_code=404, detail="Content ID not found in current data")
    
    content_row = content_subset.iloc[0]
    m = req.match
    
    # Build output row based on requested columns
    out_row = {
        "contentid": str(content_row.get("contentid", "")),
        "contentname": str(content_row.get("contentname", "")),
        "contenttype": str(content_row.get("contenttype", "")),
        "language": str(content_row.get("language", "")),
        "releaseyear": str(content_row.get("releaseyear", "")),
        "source_1_rating": str(m.get("imdb_rating", "")).replace("nan", ""),
        "Manual_Genre": req.manual_genre if req.manual_genre is not None else str(m.get("genres", "")).replace("nan", ""),
        "Manual_Keywords": req.manual_keywords if req.manual_keywords is not None else "",
        "Updated_release_year": str(m.get("release_date", "")).split("-")[0] if str(m.get("release_date", "")) else "",
        "Original_Language": str(m.get("original_language", "")).replace("nan", ""),
        "IMDB ID": str(m.get("imdb_id", "")).replace("nan", ""),
        "TMDB ID": str(m.get("tmdb_id") or m.get("id", "")).replace("nan", ""),
        "Partner_Genre": str(content_row.get("genre", "")).replace("nan", ""),
        "cast": str(content_row.get("cast", "")).replace("nan", ""),
        "Partner": str(content_row.get("partnername", "")),
        "Date": str(content_row.get("created_on", ""))
    }
    date_str  = datetime.now().strftime("%d%m%Y")
    out_file = rf"r:\meta_enr\enrichment_{date_str}.csv"
    file_exists = os.path.isfile(out_file)
    
    try:
        with open(out_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(out_row.keys()))
            if not file_exists:
                writer.writeheader()
            writer.writerow(out_row)
    except Exception as e:
        logger.error("Failed writing to CSV: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to save CSV: {e}")
        
    return {"status": "success", "message": f"Saved {req.contentid} match to CSV"}

@app.post("/remove_match", summary="Remove a selected match from local CSV")
def remove_match(req: RemoveMatchRequest):
    date_str  = datetime.now().strftime("%d%m%Y")
    out_file = rf"r:\meta_enr\enrichment_{date_str}.csv"
    if not os.path.isfile(out_file):
        return {"status": "success", "message": "No CSV file exists yet"}
        
    try:
        # Read the existing CSV into memory
        with open(out_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames
            
        if not fieldnames:
            return {"status": "success", "message": "CSV is empty, nothing to remove"}

        # Filter out the requested contentid
        new_rows = [r for r in rows if r.get("contentid") != req.contentid]
        
        # Write back (extrasaction='ignore' handles trailing-comma rows where
        # csv.DictReader stores extra values under the None key)
        clean_rows = [{k: v for k, v in r.items() if k is not None} for r in new_rows]
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(clean_rows)
            
    except Exception as e:
        logger.error("Failed removing from CSV: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to remove from CSV: {e}")
        
    return {"status": "success", "message": f"Removed {req.contentid} from CSV"}

MANUAL_ENRICH_FIELDNAMES = [
    "contentid", "contentname", "contenttype", "language", "releaseyear",
    "source_1_rating", "Manual_Genre", "Manual_Keywords", "Updated_release_year",
    "Original_Language", "IMDB ID", "TMDB ID", "Partner_Genre", "cast", "Partner", "Date",
]

@app.post("/manual_enrich", summary="Save content to manual enrichment CSV")
def manual_enrich(req: ManualEnrichRequest):
    try:
        df = _get_df(req.project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    content_subset = df[df["contentid"] == req.contentid]
    if content_subset.empty:
        raise HTTPException(status_code=404, detail="Content ID not found in current data")

    content_row = content_subset.iloc[0]

    out_row = {field: "" for field in MANUAL_ENRICH_FIELDNAMES}
    out_row["contentid"]    = str(content_row.get("contentid", ""))
    out_row["contentname"]  = str(content_row.get("contentname", ""))
    out_row["contenttype"]  = str(content_row.get("contenttype", ""))
    out_row["Partner"]      = str(content_row.get("partnername", ""))
    out_row["cast"]         = str(content_row.get("cast", "")).replace("nan", "")
    out_row["Partner_Genre"]= str(content_row.get("genre", "")).replace("nan", "")
    out_row["Date"]         = datetime.now().strftime("%Y-%m-%d")

    date_str  = datetime.now().strftime("%d%m%Y")
    out_file  = rf"r:\meta_enr\manual_enrichment_{date_str}.csv"
    file_exists = os.path.isfile(out_file)

    try:
        with open(out_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=MANUAL_ENRICH_FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerow(out_row)
    except Exception as e:
        logger.error("Failed writing manual enrichment CSV: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to save manual enrichment: {e}")

    return {"status": "success", "message": f"Saved {req.contentid} to {os.path.basename(out_file)}"}

@app.post("/remove_manual_enrich", summary="Remove a row from today's manual enrichment CSV")
def remove_manual_enrich(req: ManualEnrichRequest):
    date_str = datetime.now().strftime("%d%m%Y")
    out_file = rf"r:\meta_enr\manual_enrichment_{date_str}.csv"

    if not os.path.isfile(out_file):
        return {"status": "success", "message": "No manual enrichment file for today"}

    try:
        with open(out_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames

        if not fieldnames:
            return {"status": "success", "message": "File is empty"}

        clean_rows = [{k: v for k, v in r.items() if k is not None}
                      for r in rows if r.get("contentid") != req.contentid]

        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(clean_rows)
    except Exception as e:
        logger.error("Failed removing from manual enrichment CSV: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to remove: {e}")

    return {"status": "success", "message": f"Removed {req.contentid} from {os.path.basename(out_file)}"}

_RAPIDAPI_KEY  = "1a4a28539dmshaf707bc96c0f125p1a55a4jsn08895e1b32ce"
_RAPIDAPI_HOST = "imdb236.p.rapidapi.com"
_RAPIDAPI_HEADERS = {"x-rapidapi-host": _RAPIDAPI_HOST, "x-rapidapi-key": _RAPIDAPI_KEY}


def _fetch_imdb_detail(imdb_id: str) -> dict:
    """Fetch full IMDB detail for one title. Returns {} on failure."""
    try:
        r = http_requests.get(
            f"https://{_RAPIDAPI_HOST}/api/imdb/{imdb_id}",
            headers=_RAPIDAPI_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def _extract_detail(detail: dict) -> dict:
    """Pull director, cast, imdb_rating, genres, original_language from a detail response."""
    directors = detail.get("directors", [])
    director_str = ", ".join(d.get("fullName", "") for d in directors if d.get("fullName"))

    cast_members = [
        c.get("fullName", "")
        for c in detail.get("cast", [])
        if c.get("job") in ("actor", "actress") and c.get("fullName")
    ]
    cast_str = ", ".join(cast_members[:5])  # top 5 billed actors

    genres = detail.get("genres", [])
    genres_str = ", ".join(genres) if isinstance(genres, list) else str(genres)

    spoken = detail.get("spokenLanguages", [])
    lang_str = spoken[0] if spoken else ""

    return {
        "director":          director_str,
        "cast":              cast_str,
        "genres":            genres_str,
        "imdb_rating":       str(detail.get("averageRating", "")),
        "original_language": lang_str,
    }


@app.post("/advanced_search", summary="IMDB autocomplete + detail fetch for director/cast")
def advanced_search(req: AdvancedSearchRequest):
    from concurrent.futures import ThreadPoolExecutor

    try:
        df = _get_df(req.project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    rows = df[df["contentid"] == req.contentid]
    if rows.empty:
        raise HTTPException(status_code=404, detail="Content ID not found")

    row      = rows.iloc[0]
    fullname = str(row.get("contentname", ""))
    director = str(row.get("director", "")).strip().lower()

    # Extract title before the first ' - ' or ' : ' (spaced separators only,
    # so hyphens/colons inside words like "Spider-Man" are preserved)
    query = re.split(r"\s+[-:]\s+", fullname, maxsplit=1)[0].strip() or fullname.strip()

    # ── Step 1: autocomplete ──────────────────────────────────────────────────
    try:
        resp = http_requests.get(
            f"https://{_RAPIDAPI_HOST}/api/imdb/autocomplete",
            params={"query": query},
            headers=_RAPIDAPI_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IMDB autocomplete error: {e}")

    items = raw if isinstance(raw, list) else raw.get("results", raw.get("d", []))

    def _base(item: dict) -> dict:
        poster = item.get("primaryImage", "")
        if not poster:
            thumbs = item.get("thumbnails", [])
            if thumbs:
                poster = max(thumbs, key=lambda t: t.get("width", 0)).get("url", "")
        return {
            "imdb_id":     item.get("id", ""),
            "title":       item.get("primaryTitle", item.get("originalTitle", "")),
            "year":        str(item.get("startYear", "")),
            "type":        item.get("type", ""),
            "poster_url":  poster,
            "genres":            ", ".join(item.get("genres") or []),
            "imdb_rating":       str(item.get("averageRating", "")),
            "description":       item.get("description", ""),
            "director":          "",
            "cast":              "",
            "original_language": "",
        }

    base_results = [_base(i) for i in items if i.get("id")]

    # ── Step 2: fetch details concurrently ────────────────────────────────────
    imdb_ids = [r["imdb_id"] for r in base_results]
    with ThreadPoolExecutor(max_workers=8) as pool:
        details = list(pool.map(_fetch_imdb_detail, imdb_ids))

    for result, detail in zip(base_results, details):
        if detail:
            enriched = _extract_detail(detail)
            result["director"]          = enriched["director"]
            result["cast"]              = enriched["cast"]
            result["original_language"] = enriched["original_language"]
            # Prefer detail's genres/rating (more complete)
            if enriched["genres"]:
                result["genres"] = enriched["genres"]
            if enriched["imdb_rating"]:
                result["imdb_rating"] = enriched["imdb_rating"]

    # ── Step 3: filter by director ────────────────────────────────────────────
    if director:
        matched = [r for r in base_results if director in r["director"].lower()]
        if matched:
            base_results = matched

    return {"results": base_results, "query": query}


@app.get("/index/status", summary="FAISS index cache status")
def index_status():
    return fe.index_status()
