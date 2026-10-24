import json
import statistics
from collections import Counter

import config
from analyser import Stores, analyse_skill_gap
from embedder import embed_texts

RETRIEVAL_K = 5
MRR_K = 10
ANN_K = 10


def read_test_file(name: str) -> dict:
    return json.loads((config.TESTS_DIR / name).read_text(encoding="utf-8"))


def measure_decisions(stores: Stores, vector_store: str) -> dict:
    decision_cases = read_test_file("decision_cases.json")["cases"]

    case_results = []
    for case in decision_cases:
        analysis = analyse_skill_gap(case["has_skill_by_id"], case["occupation_id"], stores, vector_store)
        essential_skills = analysis["evidence"]["essential_skills"]
        case_results.append(
            {
                "id": case["id"],
                "expected_verdict": case["expected_verdict"],
                "verdict": analysis["verdict"],
                "lacking_matches": sorted(
                    skill["skill_id"] for skill in essential_skills if skill["state"] == "lacking"
                )
                == case["expected_lacking_skill_ids"],
                "covered_matches": sorted(
                    skill["skill_id"] for skill in essential_skills if skill["state"] == "covered"
                )
                == case["expected_covered_skill_ids"],
            }
        )

    case_count = len(case_results)
    confusion = Counter((result["expected_verdict"], result["verdict"]) for result in case_results)
    return {
        "case_count": case_count,
        "verdict_accuracy": sum(result["verdict"] == result["expected_verdict"] for result in case_results)
        / case_count,
        "lacking_skills_exact": sum(result["lacking_matches"] for result in case_results) / case_count,
        "covered_skills_exact": sum(result["covered_matches"] for result in case_results) / case_count,
        "verdict_confusion": {
            f"{expected} -> {actual}": count for (expected, actual), count in sorted(confusion.items())
        },
        "cases": case_results,
    }


def measure_retrieval(stores: Stores) -> dict:
    queries = read_test_file("retrieval_queries.json")["queries"]
    query_vectors = embed_texts([query["text"] for query in queries])

    results = {}
    for system_name, search in [("qdrant", stores.qdrant), ("pgvector", stores.pgvector)]:
        hits, reciprocal_ranks, misses = [], [], []
        for query, query_vector in zip(queries, query_vectors, strict=True):
            similar_occupations, _ = search.fetch_similar_concepts(query_vector, kind="occupation", limit=MRR_K)
            ranked_ids = [occupation["concept_id"] for occupation in similar_occupations]
            relevant_id = query["relevant_occupation_id"]
            hits.append(relevant_id in ranked_ids[:RETRIEVAL_K])
            reciprocal_ranks.append(1 / (ranked_ids.index(relevant_id) + 1) if relevant_id in ranked_ids else 0.0)
            if relevant_id not in ranked_ids[:RETRIEVAL_K]:
                misses.append(f"{query['id']} '{query['text']}' -> {relevant_id}, got {ranked_ids[:3]}")
        results[system_name] = {
            "recall_at_5": statistics.mean(hits),
            "mrr_at_10": statistics.mean(reciprocal_ranks),
            "misses": misses,
        }
    return results


def measure_ann(stores: Stores) -> dict:
    retrieval_tests = read_test_file("retrieval_queries.json")
    query_vectors = embed_texts([query["text"] for query in retrieval_tests["queries"]])
    filter_group = retrieval_tests["filter_isco_minor_group_for_5_percent"]
    kept_share = stores.pgvector.fetch_concept_count(filter_group) / stores.pgvector.fetch_concept_count()

    systems = {"qdrant": stores.qdrant, "pgvector": stores.pgvector}
    report: dict[str, object] = {"filter": {"isco_minor_group": filter_group, "kept_share": round(kept_share, 3)}}
    hnsw_top10_by_system = {}
    for system_name, search in systems.items():
        unfiltered_recalls, filtered_recalls, filtered_counts, filtered_latencies, top10_lists = [], [], [], [], []
        for query_vector in query_vectors:
            hnsw_concepts, _ = search.fetch_similar_concepts(query_vector, limit=ANN_K)
            exact_concepts, _ = search.fetch_similar_concepts(query_vector, limit=ANN_K, exact=True)
            unfiltered_recalls.append(_count_shared_ids(hnsw_concepts, exact_concepts) / ANN_K)
            top10_lists.append([concept["concept_id"] for concept in hnsw_concepts])

            filtered_hnsw, elapsed_ms = search.fetch_similar_concepts(
                query_vector, isco_minor_group=filter_group, limit=ANN_K
            )
            filtered_exact, _ = search.fetch_similar_concepts(
                query_vector, isco_minor_group=filter_group, limit=ANN_K, exact=True
            )
            filtered_counts.append(len(filtered_hnsw))
            filtered_recalls.append(_count_shared_ids(filtered_hnsw, filtered_exact) / max(len(filtered_exact), 1))
            filtered_latencies.append(elapsed_ms)

        hnsw_top10_by_system[system_name] = top10_lists
        report[system_name] = {
            "settings": search.fetch_concept_vector_settings(),
            "ann_recall_at_10": statistics.mean(unfiltered_recalls),
            "filtered_results_returned_mean": statistics.mean(filtered_counts),
            "filtered_ann_recall_at_10": statistics.mean(filtered_recalls),
            "filtered_latency_ms_mean": round(statistics.mean(filtered_latencies), 2),
        }

    shared_counts = [
        len(set(qdrant_ids) & set(pgvector_ids))
        for qdrant_ids, pgvector_ids in zip(
            hnsw_top10_by_system["qdrant"], hnsw_top10_by_system["pgvector"], strict=True
        )
    ]
    report["shared_ids_qdrant_vs_pgvector_top10_mean"] = statistics.mean(shared_counts)
    report["query_count"] = len(query_vectors)
    return report


def _count_shared_ids(first_concepts: list, second_concepts: list) -> int:
    first_ids = {concept["concept_id"] for concept in first_concepts}
    return len(first_ids & {concept["concept_id"] for concept in second_concepts})


def compare_joined_query(stores: Stores, person_id: int, text: str) -> dict:
    query_vector = embed_texts([text])[0]

    pgvector_rows = stores.pgvector.fetch_similar_skills_with_person_statements(query_vector, person_id)

    qdrant_skills, _ = stores.qdrant.fetch_similar_concepts(query_vector, kind="skill", limit=ANN_K)
    has_skill_by_id = stores.postgres.fetch_person_skill_statements(person_id)
    qdrant_rows = [
        {
            "skill_id": skill["concept_id"],
            "label": skill["label"],
            "skill_type": skill["skill_type"],
            "score": skill["score"],
            "has_skill": has_skill_by_id.get(skill["concept_id"]),
        }
        for skill in qdrant_skills
    ]
    return {"pgvector_single_statement": pgvector_rows, "qdrant_then_postgres": qdrant_rows}
