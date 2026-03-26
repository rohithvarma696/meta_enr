import os
import logging
import numpy as np
import pandas as pd
import faiss
from sentence_transformers import SentenceTransformer

from config import CACHE_DIR, MODEL_NAME, TOP_K, TMDB_CSV
from normalizer import normalize_name

logger = logging.getLogger(__name__)

# Cached objects — built once and reused across requests
_model       = None
_faiss_index = None
_df_meta     = None   # metadata DataFrame with original values preserved

CACHE_FAISS   = os.path.join(CACHE_DIR, "tmdb.faiss")
CACHE_EMB     = os.path.join(CACHE_DIR, "tmdb_embeddings.npy")
CACHE_META    = os.path.join(CACHE_DIR, "tmdb_meta.parquet")


# ── helpers 

def make_key(title: str, director: str) -> str:
    """Build a combined lookup key (same logic as the original FAISS script)."""
    return f"{str(title).strip().lower()} {str(director).strip().lower()}"


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading embedding model …")
        _model = SentenceTransformer(MODEL_NAME)
    return _model


# ── index build / load 

def _build_and_cache_index(df_meta: pd.DataFrame):
    """Encode the TMDB catalogue and save FAISS index + embeddings + meta to disk."""
    model = _get_model()

    # Keep original director for display; normalise for key building
    df_meta = df_meta.copy()
    df_meta["director_original"] = df_meta["director"].copy()
    df_meta["director"]          = df_meta["director"].apply(normalize_name)
    df_meta["cast"]              = df_meta["cast"].apply(normalize_name)

    meta_keys = df_meta.apply(
        lambda r: make_key(r["title"], r["director"]), axis=1
    ).tolist()

    logger.info("Encoding TMDB catalogue (%d items) …", len(meta_keys))
    meta_embeddings = model.encode(
        meta_keys, normalize_embeddings=True, show_progress_bar=True
    )
    meta_embeddings = np.array(meta_embeddings, dtype="float32")

    # Build FAISS inner-product index (cosine after L2-normalising)
    dim   = meta_embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(meta_embeddings)
    logger.info("FAISS index built — %d vectors, dim=%d", index.ntotal, dim)

    # Persist everything
    faiss.write_index(index, CACHE_FAISS)
    np.save(CACHE_EMB, meta_embeddings)
    df_meta.to_parquet(CACHE_META, index=False)
    logger.info("Index cached to %s", CACHE_DIR)

    return index, df_meta


def _load_index():
    """Load FAISS index + meta from disk cache if it exists."""
    if os.path.exists(CACHE_FAISS) and os.path.exists(CACHE_META):
        logger.info("Loading FAISS index from cache …")
        index   = faiss.read_index(CACHE_FAISS)
        df_meta = pd.read_parquet(CACHE_META)
        return index, df_meta
    return None, None


def get_or_build_index():
    """Return (index, df_meta) — load from cache or build from TMDB CSV."""
    global _faiss_index, _df_meta

    if _faiss_index is not None and _df_meta is not None:
        return _faiss_index, _df_meta

    # Try disk cache first
    index, df_meta = _load_index()
    if index is not None:
        _faiss_index = index
        _df_meta     = df_meta
        return _faiss_index, _df_meta

    # Build from raw CSV
    logger.info("Reading TMDB CSV: %s", TMDB_CSV)
    df_raw = pd.read_csv(TMDB_CSV)

    # Keep only the columns we need
    keep_cols = [
        "id", "title", "director", "cast",
        "imdb_rating", "release_date", "genres",
        "overview", "poster_path", "original_language", "imdb_id"
    ]
    df_raw = df_raw[[c for c in keep_cols if c in df_raw.columns]].copy()
    df_raw.dropna(subset=["title"], inplace=True)
    df_raw["director"] = df_raw["director"].fillna("")

    _faiss_index, _df_meta = _build_and_cache_index(df_raw)
    return _faiss_index, _df_meta


# ── search 

def search(df_query: pd.DataFrame) -> list[dict]:
    """
    Run FAISS similarity search on a query DataFrame.

    df_query must have columns: title, director, contentid
    Returns a list of dicts — one dict per query row, containing the content
    info plus a 'matches' list of top-K metadata hits.
    """
    index, df_meta = get_or_build_index()
    model          = _get_model()

    # Normalise query directors the same way as meta
    df_query = df_query.copy()
    df_query["director_norm"] = df_query["director"].apply(normalize_name)

    query_keys = df_query.apply(
        lambda r: make_key(r["title"], r["director_norm"]), axis=1
    ).tolist()

    logger.info("Encoding %d query items …", len(query_keys))
    query_embeddings = model.encode(
        query_keys, normalize_embeddings=True, show_progress_bar=False
    )
    query_embeddings = np.array(query_embeddings, dtype="float32")

    top_k = min(TOP_K, len(df_meta))
    scores, indices = index.search(query_embeddings, top_k)

    def _safe_str(v):
        if pd.isna(v): return ""
        s = str(v)
        return "" if s.lower() == "nan" else s

    def _safe_float(v):
        if pd.isna(v): return None
        return float(v)

    results = []
    for q_idx, q_row in enumerate(df_query.itertuples(index=False)):
        matches = []
        for rank, (meta_idx, score) in enumerate(
            zip(indices[q_idx], scores[q_idx]), start=1
        ):
            meta_row = df_meta.iloc[meta_idx]
            poster   = _safe_str(meta_row.get("poster_path", ""))
            poster_url = (
                f"https://image.tmdb.org/t/p/w780{poster}"
                if poster
                else ""
            )
            matches.append({
                "rank":              rank,
                "similarity":        round(float(score), 4),
                "id":                _safe_str(meta_row.get("id", "")),
                "imdb_id":           _safe_str(meta_row.get("imdb_id", "")),
                "original_language": _safe_str(meta_row.get("original_language", "")),
                "title":             _safe_str(meta_row.get("title", "")),
                "director":          _safe_str(meta_row.get("director_original", meta_row.get("director", ""))),
                "cast":              _safe_str(meta_row.get("cast", "")),
                "imdb_rating":       _safe_float(meta_row.get("imdb_rating")),
                "genres":            _safe_str(meta_row.get("genres", "")),
                "release_date":      _safe_str(meta_row.get("release_date", "")),
                "overview":          _safe_str(meta_row.get("overview", "")),
                "poster_url":        poster_url,
            })

        results.append({
            "contentid":   _safe_str(getattr(q_row, "contentid", "")),
            "contentname": _safe_str(getattr(q_row, "title", "")),
            "director":    _safe_str(getattr(q_row, "director", "")),
            "cast":        _safe_str(getattr(q_row, "cast", "")),
            "imgurl":      _safe_str(getattr(q_row, "imgurl", "")),
            "matches":     matches,
        })

    return results


def index_status() -> dict:
    """Return current state of the FAISS index."""
    cached = os.path.exists(CACHE_FAISS) and os.path.exists(CACHE_META)
    loaded = _faiss_index is not None
    total  = int(_faiss_index.ntotal) if loaded else 0
    return {
        "disk_cache_exists": cached,
        "index_loaded":      loaded,
        "total_vectors":     total,
    }
