from dataclasses import dataclass
from datetime import UTC, datetime

from embedder import build_concept_embedding_text, build_concept_vector_rows, embed_texts
from stores.mongo_store import MongoStore
from stores.neo4j_store import Neo4jStore
from stores.pgvector_store import PgVectorStore
from stores.postgres_store import PostgresStore
from stores.qdrant_store import QdrantStore
from stores.redis_store import RedisStore

RULE_VERSION = "gap-v1"
SIMILAR_OCCUPATION_LIMIT = 6
ALTERNATIVE_COUNT = 3
REASON_LABEL_COUNT = 3
UPDATABLE_OCCUPATION_FIELDS = {"essential_skill_ids", "optional_skill_ids", "description"}


@dataclass
class Stores:
    postgres: PostgresStore
    mongo: MongoStore
    redis: RedisStore
    neo4j: Neo4jStore
    pgvector: PgVectorStore
    qdrant: QdrantStore


def connect_stores() -> Stores:
    return Stores(PostgresStore(), MongoStore(), RedisStore(), Neo4jStore(), PgVectorStore(), QdrantStore())


def analyse_skill_gap(
    has_skill_by_id: dict[str, bool], occupation_id: str, stores: Stores, vector_store: str = "qdrant"
) -> dict:
    occupation = stores.mongo.fetch_occupation(occupation_id)
    held_skill_ids = sorted(skill_id for skill_id, has_skill in has_skill_by_id.items() if has_skill)

    essential_skill_ids = occupation["essential_skill_ids"]
    narrower_held_by_skill = stores.neo4j.fetch_held_narrower_skill_ids(essential_skill_ids, held_skill_ids)
    essential_states = classify_essential_skills(essential_skill_ids, has_skill_by_id, narrower_held_by_skill)
    optional_held_ids = [skill_id for skill_id in occupation["optional_skill_ids"] if has_skill_by_id.get(skill_id)]

    labelled_skill_ids = [*essential_skill_ids, *optional_held_ids, *held_skill_ids]
    skill_labels = stores.postgres.fetch_skill_labels_by_id(labelled_skill_ids)
    verdict, verdict_reason = decide_readiness(essential_states, skill_labels)

    alternatives = fetch_alternative_occupations_by_readiness(occupation, has_skill_by_id, stores, vector_store)

    essential_skills = [
        {
            "skill_id": skill_id,
            "label": skill_labels[skill_id],
            "state": state,
            "covered_by": [
                {"skill_id": narrower_id, "label": skill_labels[narrower_id]}
                for narrower_id in narrower_held_by_skill.get(skill_id, [])
            ]
            if state == "covered"
            else [],
        }
        for skill_id, state in essential_states.items()
    ]
    updated_at = occupation.get("updated_at")
    evidence = {
        "essential_skills": essential_skills,
        "optional_skills_held": [
            {"skill_id": skill_id, "label": skill_labels[skill_id]} for skill_id in optional_held_ids
        ],
        "optional_skill_count": len(occupation["optional_skill_ids"]),
        "alternatives": alternatives,
        "statement_count": len(has_skill_by_id),
        "occupation_document_updated_at": updated_at.isoformat() if updated_at else None,
    }
    return {
        "occupation_id": occupation_id,
        "occupation_label": occupation["preferred_label"]["en"],
        "occupation_label_hu": occupation["preferred_label"].get("hu"),
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "rule_version": RULE_VERSION,
        "vector_store": vector_store,
        "evidence": evidence,
    }


def classify_essential_skills(
    essential_skill_ids: list[str], has_skill_by_id: dict[str, bool], narrower_held_by_skill: dict[str, list[str]]
) -> dict[str, str]:
    essential_states = {}
    for skill_id in essential_skill_ids:
        stated = has_skill_by_id.get(skill_id)
        if stated is True:
            essential_states[skill_id] = "held"
        elif stated is False:
            essential_states[skill_id] = "lacking"
        elif narrower_held_by_skill.get(skill_id):
            essential_states[skill_id] = "covered"
        else:
            essential_states[skill_id] = "not_stated"
    return essential_states


def decide_readiness(essential_states: dict[str, str], skill_labels: dict[str, str]) -> tuple[str, str]:
    lacking_ids = [skill_id for skill_id, state in essential_states.items() if state == "lacking"]
    if lacking_ids:
        return "GAP", f"{len(lacking_ids)} essential skills missing: {_summarise_labels(lacking_ids, skill_labels)}"

    not_stated_ids = [skill_id for skill_id, state in essential_states.items() if state == "not_stated"]
    if not_stated_ids:
        return (
            "UNKNOWN",
            f"{len(not_stated_ids)} essential skills not stated: {_summarise_labels(not_stated_ids, skill_labels)}",
        )
    return "READY", "every essential skill is held or covered by a held narrower skill"


def _summarise_labels(skill_ids: list[str], skill_labels: dict[str, str]) -> str:
    shown_labels = ", ".join(skill_labels.get(skill_id, skill_id) for skill_id in skill_ids[:REASON_LABEL_COUNT])
    hidden_count = len(skill_ids) - REASON_LABEL_COUNT
    return f"{shown_labels} and {hidden_count} more" if hidden_count > 0 else shown_labels


def fetch_alternative_occupations_by_readiness(
    occupation: dict, has_skill_by_id: dict[str, bool], stores: Stores, vector_store: str
) -> list[dict]:
    query_vector = embed_texts([build_concept_embedding_text(occupation)])[0]
    search = stores.qdrant if vector_store == "qdrant" else stores.pgvector
    similar_occupations, _ = search.fetch_similar_concepts(
        query_vector, kind="occupation", limit=SIMILAR_OCCUPATION_LIMIT + 1
    )
    similarity_by_id = {
        similar["concept_id"]: similar["score"]
        for similar in similar_occupations
        if similar["concept_id"] != occupation["_id"]
    }

    graph_occupations = stores.neo4j.fetch_occupations_essential_skill_ids(list(similarity_by_id))
    required_skill_ids = sorted(
        {skill_id for graph in graph_occupations.values() for skill_id in graph["essential_skill_ids"]}
    )
    held_skill_ids = sorted(skill_id for skill_id, has_skill in has_skill_by_id.items() if has_skill)
    narrower_held_by_skill = stores.neo4j.fetch_held_narrower_skill_ids(required_skill_ids, held_skill_ids)

    alternatives = []
    for occupation_id, graph_occupation in graph_occupations.items():
        states = classify_essential_skills(
            graph_occupation["essential_skill_ids"], has_skill_by_id, narrower_held_by_skill
        )
        state_values = list(states.values())
        met_count = state_values.count("held") + state_values.count("covered")
        verdict, _ = decide_readiness(states, {})
        alternatives.append(
            {
                "occupation_id": occupation_id,
                "label": graph_occupation["label"],
                "similarity": round(similarity_by_id[occupation_id], 3),
                "verdict": verdict,
                "essential_total": len(state_values),
                "essential_met": met_count,
                "essential_lacking": state_values.count("lacking"),
                "graph_refreshed_at": graph_occupation["refreshed_at"],
            }
        )
    alternatives.sort(
        key=lambda alternative: (
            -alternative["essential_met"] / alternative["essential_total"],
            -alternative["similarity"],
        )
    )
    return alternatives[:ALTERNATIVE_COUNT]


def add_logged_gap_analysis(person_id: int, occupation_id: str, stores: Stores, vector_store: str = "qdrant") -> dict:
    has_skill_by_id = stores.postgres.fetch_person_skill_statements(person_id)

    analysis = analyse_skill_gap(has_skill_by_id, occupation_id, stores, vector_store)
    analysis["person_id"] = person_id
    analysis["analysis_id"] = stores.postgres.add_gap_analysis(analysis)
    stores.redis.set_cached_analysis(person_id, occupation_id, analysis)
    return analysis


def fetch_person_gap_analysis_cache_aside(person_id: int, occupation_id: str, stores: Stores) -> tuple[dict, str]:
    cached_analysis = stores.redis.fetch_cached_analysis(person_id, occupation_id)
    if cached_analysis is not None:
        return cached_analysis, "hit"

    return add_logged_gap_analysis(person_id, occupation_id, stores), "miss"


def set_person_skill_statement(person_id: int, skill_id: str, has_skill: bool | None, stores: Stores) -> int:
    if has_skill is None:
        stores.postgres.remove_person_skill_statement(person_id, skill_id)
    else:
        stores.postgres.upsert_person_skill_statement(person_id, skill_id, has_skill)

    return stores.redis.delete_person_cached_analyses(person_id)


def update_occupation_document(occupation_id: str, fields: dict, stores: Stores) -> int:
    if not fields.keys() <= UPDATABLE_OCCUPATION_FIELDS:
        raise ValueError(f"only {sorted(UPDATABLE_OCCUPATION_FIELDS)} can change; labels are keys in PostgreSQL")
    skill_ids = [*fields.get("essential_skill_ids", []), *fields.get("optional_skill_ids", [])]
    unknown_skill_ids = set(skill_ids) - set(stores.postgres.fetch_skill_labels_by_id(skill_ids))
    if unknown_skill_ids:
        raise ValueError(f"unknown skills: {sorted(unknown_skill_ids)}")

    occupation = stores.mongo.update_occupation_fields(occupation_id, fields)

    refreshed_at = datetime.now(UTC)
    stores.neo4j.refresh_occupation(occupation, refreshed_at)
    concept_vector_row = build_concept_vector_rows([occupation], [], refreshed_at)[0]
    stores.pgvector.upsert_concept_vector(concept_vector_row)
    stores.qdrant.upsert_concept_vector(concept_vector_row)
    return stores.redis.delete_occupation_cached_analyses(occupation_id)
