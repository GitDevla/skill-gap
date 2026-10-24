import json
from datetime import UTC, datetime

import typer

import dataset
import demos
import measure
from analyser import add_logged_gap_analysis, connect_stores
from embedder import build_concept_vector_rows
from stores.neo4j_store import build_graph_source_rows

app = typer.Typer(no_args_is_help=True, help="Skill gap service commands.")


@app.command("fetch")
def download_and_build_seed_files() -> None:
    """Download the ESCO ICT occupations and skills and rebuild the data/seed files."""
    dataset.download_raw_esco()
    row_counts = dataset.build_seed_files()
    for name, count in row_counts.items():
        typer.echo(f"{name}: {count}")


@app.command("seed")
def reset_and_load_all_stores() -> None:
    """Wipe every database, reload it from data/seed and analyse every person against their target occupation."""
    tables, occupation_documents, skill_documents = dataset.read_seed_files()
    stores = connect_stores()

    stores.postgres.reset_and_load_tables(tables)
    stores.mongo.reset_and_load_esco_documents(occupation_documents, skill_documents)
    stores.redis.clear_all_analyses()

    refreshed_at = datetime.now(UTC)
    graph_source_rows = build_graph_source_rows(occupation_documents, skill_documents)
    stores.neo4j.reset_and_load_graph(graph_source_rows, refreshed_at)

    concept_vector_rows = build_concept_vector_rows(occupation_documents, skill_documents, refreshed_at)
    stores.pgvector.reset_and_load_concept_vectors(concept_vector_rows)
    stores.qdrant.reset_and_load_concept_vectors(concept_vector_rows)

    for person in tables["people"]:
        add_logged_gap_analysis(int(person["id"]), person["target_occupation_id"], stores)

    postgres_row_count = sum(len(table_rows) for table_rows in tables.values())
    typer.echo(
        f"loaded: {postgres_row_count} PostgreSQL rows, {len(occupation_documents) + len(skill_documents)} ESCO "
        f"documents, {len(concept_vector_rows)} concept vectors, {len(tables['people'])} gap analyses"
    )


@app.command("update-demo")
def run_update_demo() -> None:
    """Change one occupation document in MongoDB and show its Redis, Neo4j and vector copies until refreshed."""
    demos.run_update_demo(connect_stores(), typer.echo)


@app.command("measure")
def print_measurements() -> None:
    """Run the frozen test cases and the pgvector/Qdrant comparison; print every number in the report."""
    stores = connect_stores()

    for vector_store in ["qdrant", "pgvector"]:
        decisions = measure.measure_decisions(stores, vector_store)
        typer.echo(f"== decisions ({vector_store}, {decisions['case_count']} cases)")
        for result in decisions["cases"]:
            mark = "ok " if result["verdict"] == result["expected_verdict"] else "BAD"
            typer.echo(
                f"{mark} {result['id']:<4} expected {result['expected_verdict']:<8} got {result['verdict']:<8} "
                f"lacking match {result['lacking_matches']}, covered match {result['covered_matches']}"
            )
        for name in ["verdict_accuracy", "lacking_skills_exact", "covered_skills_exact"]:
            typer.echo(f"{name}: {decisions[name]:.3f}")
        typer.echo(f"verdict confusion: {decisions['verdict_confusion']}")

    typer.echo("== occupation retrieval (20 ESCO alternative labels, kind = occupation)")
    typer.echo(json.dumps(measure.measure_retrieval(stores), indent=2))

    typer.echo("== pgvector vs Qdrant (20 fixed queries over all concepts)")
    typer.echo(json.dumps(measure.measure_ann(stores), indent=2, default=str))

    typer.echo("== one query: pgvector joined in SQL vs Qdrant then PostgreSQL (person 1)")
    joined = measure.compare_joined_query(stores, 1, "I build websites with JavaScript and design page layouts")
    typer.echo(json.dumps(joined, indent=2, default=str))


if __name__ == "__main__":
    app()
