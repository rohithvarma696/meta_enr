import os

# Root folders
CONTENTS_ROOT = r"r:\meta_enr\contents"
TMDB_CSV      = r"r:\meta_enr\TMDB_all_movies.csv"
CACHE_DIR        = r"r:\meta_enr\app\cache"
CACHE_DUBBED_DIR = r"r:\meta_enr\app\cache_dubbed"

# FAISS / model settings
MODEL_NAME = "all-mpnet-base-v2"
TOP_K        = 10   # top matches per content (FAISS title+director)
TOP_K_DUBBED = 15   # top matches for dubbed content search (director+cast)

# Hardcoded today for now — swap with datetime.today().strftime("%Y%m%d") later
TODAY = "20260213"

# Make sure cache folder exists
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(CACHE_DUBBED_DIR, exist_ok=True)
