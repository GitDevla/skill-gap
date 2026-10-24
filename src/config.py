import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://skill:skill@localhost:25432/skill")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://skill:skill@localhost:27019/?authSource=admin")
MONGO_DB = "skill"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6381/0")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7689")
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "skill-pass"
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6336")
ANALYSIS_CACHE_TTL_SECONDS = 3600

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

RAW_DIR = ROOT / "data" / "raw"
SEED_DIR = ROOT / "data" / "seed"
TESTS_DIR = ROOT / "data" / "tests"
WEB_DIST_DIR = ROOT / "web" / "dist"
