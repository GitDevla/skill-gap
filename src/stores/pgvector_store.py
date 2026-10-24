import time

import psycopg
from psycopg.rows import DictRow, dict_row

import config

SCHEMA = """
CREATE EXTENSION vector;
CREATE TABLE concept_embeddings (
    concept_id text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('occupation', 'skill')),
    label text NOT NULL,
    isco_minor_group text CHECK (isco_minor_group ~ '^[0-9]{3}$'),
    skill_type text CHECK (skill_type IN ('skill', 'knowledge')),
    embedding vector(384) NOT NULL,
    source_id text NOT NULL,
    refreshed_at timestamptz NOT NULL,
    CHECK ((kind = 'occupation') = (isco_minor_group IS NOT NULL))
);
CREATE INDEX concept_embeddings_hnsw_idx ON concept_embeddings USING hnsw (embedding vector_cosine_ops);
"""
HNSW_EF_SEARCH = 40
ITERATIVE_SCAN = "strict_order"
METADATA_COLUMNS = "concept_id, kind, label, isco_minor_group, skill_type, source_id, refreshed_at"


def to_vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


class PgVectorStore:
    def __init__(self, dsn: str = config.POSTGRES_DSN):
        self.conn = psycopg.Connection[DictRow].connect(dsn, row_factory=dict_row, autocommit=True)

    def reset_and_load_concept_vectors(self, concept_vector_rows: list[dict]) -> None:
        with self.conn.transaction():
            self.conn.execute(SCHEMA)

            self._upsert_concept_vectors(concept_vector_rows)

    def upsert_concept_vector(self, concept_vector_row: dict) -> None:
        self._upsert_concept_vectors([concept_vector_row])

    def _upsert_concept_vectors(self, concept_vector_rows: list[dict]) -> None:
        insert_rows = [row | {"embedding": to_vector_literal(row["embedding"])} for row in concept_vector_rows]
        self.conn.cursor().executemany(
            """
            INSERT INTO concept_embeddings
                (concept_id, kind, label, isco_minor_group, skill_type, embedding, source_id, refreshed_at)
            VALUES (%(concept_id)s, %(kind)s, %(label)s, %(isco_minor_group)s, %(skill_type)s, %(embedding)s::vector,
                    %(source_id)s, %(refreshed_at)s)
            ON CONFLICT (concept_id) DO UPDATE
                SET label = EXCLUDED.label, isco_minor_group = EXCLUDED.isco_minor_group,
                    skill_type = EXCLUDED.skill_type, embedding = EXCLUDED.embedding,
                    refreshed_at = EXCLUDED.refreshed_at
            """,
            insert_rows,
        )

    def _set_local_hnsw_settings(self) -> None:
        self.conn.execute(
            "SELECT set_config('hnsw.ef_search', %s, true), set_config('hnsw.iterative_scan', %s, true)",
            (str(HNSW_EF_SEARCH), ITERATIVE_SCAN),
        )

    def fetch_similar_concepts(
        self,
        query_vector: list[float],
        kind: str | None = None,
        isco_minor_group: str | None = None,
        limit: int = 10,
        exact: bool = False,
    ) -> tuple[list[DictRow], float]:
        query_parameters = {
            "vector": to_vector_literal(query_vector),
            "kind": kind,
            "isco_minor_group": isco_minor_group,
            "limit": limit,
        }

        with self.conn.transaction():
            self._set_local_hnsw_settings()
            if exact:
                self.conn.execute("SET LOCAL enable_indexscan = off")
            else:
                self.conn.execute("SET LOCAL enable_seqscan = off")
                self.conn.execute("SET LOCAL enable_bitmapscan = off")
            started = time.perf_counter()
            similar_concepts = self.conn.execute(
                f"""
                SELECT {METADATA_COLUMNS}, 1 - (embedding <=> %(vector)s::vector) AS score
                FROM concept_embeddings
                WHERE (%(kind)s::text IS NULL OR kind = %(kind)s)
                  AND (%(isco_minor_group)s::text IS NULL OR isco_minor_group = %(isco_minor_group)s)
                ORDER BY embedding <=> %(vector)s::vector
                LIMIT %(limit)s
                """,
                query_parameters,
            ).fetchall()
            elapsed_ms = (time.perf_counter() - started) * 1000
        return similar_concepts, elapsed_ms

    def fetch_similar_skills_with_person_statements(
        self, query_vector: list[float], person_id: int, limit: int = 10
    ) -> list[DictRow]:
        query_parameters = {"vector": to_vector_literal(query_vector), "person_id": person_id, "limit": limit}

        with self.conn.transaction():
            self._set_local_hnsw_settings()
            return self.conn.execute(
                """
                SELECT s.id AS skill_id, s.label, s.skill_type, 1 - (c.embedding <=> %(vector)s::vector) AS score,
                       ps.has_skill
                FROM concept_embeddings c
                JOIN skills s ON s.id = c.concept_id
                LEFT JOIN person_skills ps ON ps.skill_id = s.id AND ps.person_id = %(person_id)s
                WHERE c.kind = 'skill'
                ORDER BY c.embedding <=> %(vector)s::vector
                LIMIT %(limit)s
                """,
                query_parameters,
            ).fetchall()

    def fetch_concept_vector_row(self, concept_id: str) -> DictRow:
        concept_row = self.conn.execute(
            f"SELECT {METADATA_COLUMNS} FROM concept_embeddings WHERE concept_id = %s", (concept_id,)
        ).fetchone()

        if concept_row is None:
            raise LookupError(f"concept vector {concept_id} does not exist")
        return concept_row

    def fetch_concept_count(self, isco_minor_group: str | None = None) -> int:
        count_row = self.conn.execute(
            """
            SELECT count(*) AS n FROM concept_embeddings
            WHERE %(group)s::text IS NULL OR isco_minor_group = %(group)s
            """,
            {"group": isco_minor_group},
        ).fetchone()

        assert count_row is not None
        return count_row["n"]

    def fetch_concept_vector_settings(self) -> dict:
        return {"hnsw.ef_search": HNSW_EF_SEARCH, "hnsw.iterative_scan": ITERATIVE_SCAN}

    def fetch_concept_vectors_page_without_embeddings(self, limit: int, offset: int) -> tuple[list[DictRow], int]:
        concept_rows = self.conn.execute(
            f"SELECT {METADATA_COLUMNS} FROM concept_embeddings ORDER BY refreshed_at DESC, concept_id "
            "LIMIT %s OFFSET %s",
            (limit, offset),
        ).fetchall()
        return concept_rows, self.fetch_concept_count()
