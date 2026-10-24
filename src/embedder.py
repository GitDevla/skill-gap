from datetime import datetime
from functools import cache

import config
from sentence_transformers import SentenceTransformer


@cache
def _load_model():
    return SentenceTransformer(config.EMBEDDING_MODEL, device="cpu")


def embed_texts(texts: list[str]) -> list[list[float]]:
    embeddings = _load_model().encode(texts, normalize_embeddings=True, batch_size=64)
    return embeddings.tolist()


def build_concept_embedding_text(concept_document: dict) -> str:
    return f"{concept_document['preferred_label']['en']}. {concept_document['description']['en']}"


def build_concept_vector_rows(
    occupation_documents: list[dict], skill_documents: list[dict], refreshed_at: datetime
) -> list[dict]:
    concept_documents = [("occupation", occupation) for occupation in occupation_documents]
    concept_documents += [("skill", skill) for skill in skill_documents]
    embeddings = embed_texts([build_concept_embedding_text(document) for _, document in concept_documents])

    concept_vector_rows = []
    for (kind, document), embedding in zip(concept_documents, embeddings, strict=True):
        is_occupation = kind == "occupation"
        concept_vector_rows.append(
            {
                "concept_id": document["_id"],
                "kind": kind,
                "label": document["preferred_label"]["en"],
                "isco_minor_group": document["isco_group"][:3] if is_occupation else None,
                "skill_type": None if is_occupation else document["skill_type"],
                "embedding": embedding,
                "source_id": document["_id"],
                "refreshed_at": refreshed_at,
            }
        )
    return concept_vector_rows
