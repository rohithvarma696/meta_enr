"""
FAISS engine for Dubbed Content matching.

Differs from faiss_engine.py in one key way:
  - Embedding key uses  director + cast  (not title + director)
  - Cache lives in CACHE_DUBBED_DIR
  - Shares the same SentenceTransformer model instance as faiss_engine
"""

import os
import logging

import numpy as np
import pandas as pd
import faiss

from config import CACHE_DUBBED_DIR, TOP_K_DUBBED, TMDB_CSV
from normalizer import normalize_name
from faiss_engine import _get_model   # reuse already-loaded model

logger = logging.getLogger(__name__)

# ── cache paths ───────────────────────────────────────────────────────────────
CACHE_FAISS = os.path.join(CACHE_DUBBED_DIR, "tmdb_dubbed.faiss")
CACHE_META  = os.path.join(CACHE_DUBBED_DIR, "tmdb_dubbed_meta.parquet")

# ── in-process singletons ─────────────────────────────────────────────────────
_dubbed_index = None
_dubbed_meta  = None


# ── helpers ───────────────────────────────────────────────────────────────────

def make_key(director: str, cast: str) -> str:
    """Embed key = normalised director + cast names."""
    return f"{str(director).strip().lower()} {str(cast).strip().lower()}"


# ── index build / load ────────────────────────────────────────────────────────

def _build_and_cache(df_meta: pd.DataFrame):
    model = _get_model()

    df_meta = df_meta.copy()
    df_meta["director"] = df_meta["director"].fillna("").apply(normalize_name)
    df_meta["cast"]     = df_meta["cast"].fillna("").apply(normalize_name)

    keys = df_meta.apply(
        lambda r: make_key(r["director"], r["cast"]), axis=1
    ).tolist()

    logger.info("Dubbed — encoding TMDB catalogue (%d items) …", len(keys))
    embeddings = model.encode(keys, normalize_embeddings=True, show_progress_bar=True)
    embeddings = np.array(embeddings, dtype="float32")

    dim   = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    logger.info("Dubbed FAISS index built — %d vectors, dim=%d", index.ntotal, dim)

    faiss.write_index(index, CACHE_FAISS)
    df_meta.to_parquet(CACHE_META, index=False)
    logger.info("Dubbed index cached to %s", CACHE_DUBBED_DIR)

    return index, df_meta


def _load_index():
    if os.path.exists(CACHE_FAISS) and os.path.exists(CACHE_META):
        logger.info("Loading dubbed FAISS index from cache …")
        index   = faiss.read_index(CACHE_FAISS)
        df_meta = pd.read_parquet(CACHE_META)
        if index.ntotal != len(df_meta):
            logger.warning(
                "Dubbed cache mismatch: %d vectors vs %d rows — rebuilding.",
                index.ntotal, len(df_meta),
            )
            return None, None
        return index, df_meta
    return None, None


def get_or_build_index():
    global _dubbed_index, _dubbed_meta

    if _dubbed_index is not None and _dubbed_meta is not None:
        return _dubbed_index, _dubbed_meta

    index, df_meta = _load_index()
    if index is not None:
        _dubbed_index, _dubbed_meta = index, df_meta
        return _dubbed_index, _dubbed_meta

    logger.info("Building dubbed index from TMDB CSV: %s", TMDB_CSV)
    df_raw = pd.read_csv(TMDB_CSV)

    keep_cols = [
        "id", "title", "director", "cast",
        "imdb_rating", "release_date", "genres",
        "overview", "poster_path", "original_language", "imdb_id",
    ]
    df_raw = df_raw[[c for c in keep_cols if c in df_raw.columns]].copy()
    df_raw.dropna(subset=["title"], inplace=True)
    df_raw["director"] = df_raw["director"].fillna("")
    df_raw["cast"]     = df_raw["cast"].fillna("")

    _dubbed_index, _dubbed_meta = _build_and_cache(df_raw)
    return _dubbed_index, _dubbed_meta


# ── search ────────────────────────────────────────────────────────────────────

def search(df_query: pd.DataFrame) -> list[dict]:
    """
    Run dubbed FAISS search (director + cast key) on a query DataFrame.

    df_query must have: contentid, title, director, cast
    Returns same shape as faiss_engine.search().
    """
    index, df_meta = get_or_build_index()
    model          = _get_model()

    df_query = df_query.copy()
    df_query["director"] = df_query["director"].fillna("").apply(normalize_name)
    df_query["cast"]     = df_query["cast"].fillna("").apply(normalize_name)

    query_keys = df_query.apply(
        lambda r: make_key(r["director"], r["cast"]), axis=1
    ).tolist()

    logger.info("Dubbed — encoding %d query items …", len(query_keys))
    query_emb = model.encode(query_keys, normalize_embeddings=True, show_progress_bar=False)
    query_emb = np.array(query_emb, dtype="float32")

    top_k = min(TOP_K_DUBBED, len(df_meta))
    scores, indices = index.search(query_emb, top_k)

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
            meta_row  = df_meta.iloc[meta_idx]
            poster    = _safe_str(meta_row.get("poster_path", ""))
            poster_url = (
                f"https://image.tmdb.org/t/p/w780{poster}" if poster else ""
            )
            matches.append({
                "rank":              rank,
                "similarity":        round(float(score), 4),
                "id":                _safe_str(meta_row.get("id", "")),
                "imdb_id":           _safe_str(meta_row.get("imdb_id", "")),
                "original_language": _safe_str(meta_row.get("original_language", "")),
                "title":             _safe_str(meta_row.get("title", "")),
                "director":          _safe_str(meta_row.get("director", "")),
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
    cached = os.path.exists(CACHE_FAISS) and os.path.exists(CACHE_META)
    loaded = _dubbed_index is not None
    total  = int(_dubbed_index.ntotal) if loaded else 0
    return {
        "disk_cache_exists": cached,
        "index_loaded":      loaded,
        "total_vectors":     total,
    }
