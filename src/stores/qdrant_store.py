import time
import uuid

from qdrant_client import QdrantClient, models

import config

COLLECTION = "concepts"
PAYLOAD_INDEXES = {
    "concept_id": models.PayloadSchemaType.KEYWORD,
    "kind": models.PayloadSchemaType.KEYWORD,
    "isco_minor_group": models.PayloadSchemaType.KEYWORD,
}
PAYLOAD_FIELDS = ["concept_id", "kind", "label", "isco_minor_group", "skill_type", "source_id"]
HNSW_EF = 64
INDEXING_THRESHOLD_KB = 1
FULL_SCAN_THRESHOLD_KB = 10
INDEXING_TIMEOUT_SECONDS = 120
UPSERT_BATCH_SIZE = 256


def concept_point_id(concept_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"esco-concept:{concept_id}"))


def _build_point(concept_vector_row: dict) -> models.PointStruct:
    payload = {field: concept_vector_row[field] for field in PAYLOAD_FIELDS}
    payload["refreshed_at"] = concept_vector_row["refreshed_at"].isoformat()
    point_id = concept_point_id(concept_vector_row["concept_id"])
    return models.PointStruct(id=point_id, vector=concept_vector_row["embedding"], payload=payload)


class QdrantStore:
    def __init__(self, url: str = config.QDRANT_URL):
        self.client = QdrantClient(url=url)

    def reset_and_load_concept_vectors(self, concept_vector_rows: list[dict]) -> None:
        self.client.delete_collection(COLLECTION)

        self.client.create_collection(
            COLLECTION,
            vectors_config=models.VectorParams(size=config.EMBEDDING_DIM, distance=models.Distance.COSINE),
            hnsw_config=models.HnswConfigDiff(full_scan_threshold=FULL_SCAN_THRESHOLD_KB),
            optimizers_config=models.OptimizersConfigDiff(indexing_threshold=INDEXING_THRESHOLD_KB),
            strict_mode_config=models.StrictModeConfig(
                enabled=True, unindexed_filtering_retrieve=False, unindexed_filtering_update=False
            ),
        )
        for field, schema in PAYLOAD_INDEXES.items():
            self.client.create_payload_index(COLLECTION, field, schema, wait=True)

        points = [_build_point(concept_vector_row) for concept_vector_row in concept_vector_rows]
        self._upsert_batch(points)
        self._wait_until_indexed(len(points))

    def upsert_concept_vector(self, concept_vector_row: dict) -> None:
        self.client.upsert(COLLECTION, [_build_point(concept_vector_row)], wait=True)

    def _wait_until_indexed(self, point_count: int) -> None:
        deadline = time.monotonic() + INDEXING_TIMEOUT_SECONDS
        indexed_count = self.client.get_collection(COLLECTION).indexed_vectors_count
        while indexed_count != point_count:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Qdrant indexed {indexed_count} of {point_count} vectors")
            time.sleep(0.5)
            indexed_count = self.client.get_collection(COLLECTION).indexed_vectors_count

    def _upsert_batch(self, points: list[models.PointStruct], batch_size: int = UPSERT_BATCH_SIZE) -> None:
        for batch_start in range(0, len(points), batch_size):
            batch = points[batch_start : batch_start + batch_size]
            self.client.upsert(COLLECTION, batch, wait=True)

    def fetch_similar_concepts(
        self,
        query_vector: list[float],
        kind: str | None = None,
        isco_minor_group: str | None = None,
        limit: int = 10,
        exact: bool = False,
    ) -> tuple[list[dict], float]:
        conditions = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in [("kind", kind), ("isco_minor_group", isco_minor_group)]
            if value is not None
        ]
        query_filter = models.Filter(must=list(conditions)) if conditions else None
        search_params = models.SearchParams(hnsw_ef=HNSW_EF, exact=exact)

        started = time.perf_counter()
        response = self.client.query_points(
            COLLECTION, query=query_vector, query_filter=query_filter, search_params=search_params, limit=limit
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

        similar_concepts = [(point.payload or {}) | {"score": point.score} for point in response.points]
        return similar_concepts, elapsed_ms

    def fetch_concept_payload(self, concept_id: str) -> dict:
        points = self.client.retrieve(COLLECTION, [concept_point_id(concept_id)])

        if not points or points[0].payload is None:
            raise LookupError(f"concept point {concept_id} does not exist")
        return points[0].payload

    def fetch_concept_vector_settings(self) -> dict:
        collection = self.client.get_collection(COLLECTION)
        return {"hnsw_ef": HNSW_EF, "hnsw_config": collection.config.hnsw_config.model_dump()}

    def fetch_concept_payloads_page(self, limit: int, offset: int) -> tuple[list[dict], int]:
        response = self.client.query_points(COLLECTION, limit=limit, offset=offset, with_payload=True)
        point_count = self.client.count(COLLECTION, exact=True).count

        payloads = [{"point_id": point.id} | (point.payload or {}) for point in response.points]
        return payloads, point_count
