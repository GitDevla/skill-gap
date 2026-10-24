from collections.abc import Callable

from analyser import (
    Stores,
    analyse_skill_gap,
    fetch_person_gap_analysis_cache_aside,
    update_occupation_document,
)


def run_update_demo(stores: Stores, echo: Callable[[str], None]) -> None:
    ready_analyses = stores.postgres.fetch_ready_gap_analyses()
    if not ready_analyses:
        raise RuntimeError("no READY analysis in the decision log; run `seed` first")
    person_id, occupation_id = ready_analyses[0]["person_id"], ready_analyses[0]["occupation_id"]
    occupation = stores.mongo.fetch_occupation(occupation_id)
    has_skill_by_id = stores.postgres.fetch_person_skill_statements(person_id)
    new_skill_id = next(skill_id for skill_id in occupation["optional_skill_ids"] if skill_id not in has_skill_by_id)
    new_skill_label = stores.postgres.fetch_skill_labels_by_id([new_skill_id])[new_skill_id]
    original_fields = {key: occupation[key] for key in ["essential_skill_ids", "optional_skill_ids", "description"]}
    changed_fields = {
        "essential_skill_ids": sorted([*occupation["essential_skill_ids"], new_skill_id]),
        "optional_skill_ids": [skill_id for skill_id in occupation["optional_skill_ids"] if skill_id != new_skill_id],
        "description": occupation["description"]
        | {"en": f"{occupation['description']['en']} Requires {new_skill_label}."},
    }

    analysis, cache_status = fetch_person_gap_analysis_cache_aside(person_id, occupation_id, stores)
    echo(f"1. person {person_id} -> {occupation_id}: cache {cache_status}, verdict {analysis['verdict']}")
    _echo_copies(stores, person_id, occupation_id, echo)

    stores.mongo.update_occupation_fields(occupation_id, changed_fields)
    fresh_verdict = analyse_skill_gap(has_skill_by_id, occupation_id, stores)["verdict"]
    echo(f"2. MongoDB: '{new_skill_id}' made essential and the description changed (without the update path)")
    echo(f"   a fresh analysis from the source would say {fresh_verdict}; the copies still say:")
    _echo_copies(stores, person_id, occupation_id, echo)

    invalidated_count = update_occupation_document(occupation_id, changed_fields, stores)
    analysis, cache_status = fetch_person_gap_analysis_cache_aside(person_id, occupation_id, stores)
    echo(f"3. update path: deleted {invalidated_count} cached analyses, refreshed the graph edges and both vectors")
    echo(f"   reread: cache {cache_status}, verdict {analysis['verdict']} ({analysis['verdict_reason']})")
    _echo_copies(stores, person_id, occupation_id, echo)

    invalidated_count = update_occupation_document(occupation_id, original_fields, stores)
    analysis, cache_status = fetch_person_gap_analysis_cache_aside(person_id, occupation_id, stores)
    echo(f"4. restored the original document: deleted {invalidated_count} cached analyses")
    echo(f"   reread: cache {cache_status}, verdict {analysis['verdict']}")


def _echo_copies(stores: Stores, person_id: int, occupation_id: str, echo: Callable[[str], None]) -> None:
    occupation = stores.mongo.fetch_occupation(occupation_id)
    cached = stores.redis.fetch_cached_analysis(person_id, occupation_id)
    graph_occupation = stores.neo4j.fetch_occupations_essential_skill_ids([occupation_id])[occupation_id]
    pgvector_row = stores.pgvector.fetch_concept_vector_row(occupation_id)
    qdrant_payload = stores.qdrant.fetch_concept_payload(occupation_id)

    updated_at = occupation.get("updated_at")
    source_time = f"updated {updated_at:%H:%M:%S}" if updated_at else "as fetched"
    cached_verdict = f"{cached['verdict']} (refreshed {cached['refreshed_at'][11:19]})" if cached else "(no key)"
    echo(f"   MongoDB essential skills       = {len(occupation['essential_skill_ids'])} ({source_time})")
    echo(f"   Redis cached verdict           = {cached_verdict}")
    graph_count = len(graph_occupation["essential_skill_ids"])
    echo(f"   Neo4j ESSENTIAL edges          = {graph_count} (refreshed {graph_occupation['refreshed_at'][11:19]})")
    echo(f"   pgvector embedding refreshed   = {pgvector_row['refreshed_at']:%H:%M:%S}")
    echo(f"   Qdrant point refreshed         = {qdrant_payload['refreshed_at'][11:19]}")
