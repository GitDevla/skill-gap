import re
from typing import Annotated

import psycopg
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from analyser import connect_stores, fetch_person_gap_analysis_cache_aside, set_person_skill_statement
from embedder import embed_texts
from stores.mongo_store import COLLECTION_VALIDATORS
from stores.neo4j_store import NODE_LABELS
from stores.postgres_store import BROWSABLE_TABLES

PAGE_SIZE = 25
SEARCH_LIMIT = 10
ConceptId = Annotated[str, Path(pattern=r"^[a-z0-9-]+$", max_length=200)]
SearchText = Annotated[str, Query(min_length=2, max_length=300)]

stores = connect_stores()

app = FastAPI(title="Skill gap")


class SkillStatement(BaseModel):
    has_skill: bool | None


@app.get("/api/people")
async def list_people():
    return stores.postgres.fetch_people()


@app.get("/api/occupations")
async def list_occupations():
    return stores.postgres.fetch_occupations()


@app.get("/api/occupations/search")
async def search_occupations(q: SearchText):
    query_vector = embed_texts([q])[0]
    similar_occupations, _ = stores.qdrant.fetch_similar_concepts(query_vector, kind="occupation", limit=SEARCH_LIMIT)
    return similar_occupations


@app.get("/api/occupations/{occupation_id}")
async def get_occupation(occupation_id: ConceptId):
    try:
        return stores.mongo.fetch_occupation(occupation_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@app.get("/api/people/{person_id}/analyses")
async def list_person_gap_analyses(person_id: int):
    return stores.postgres.fetch_person_gap_analyses(person_id)


@app.get("/api/people/{person_id}/analyses/{occupation_id}")
async def get_person_gap_analysis(person_id: int, occupation_id: ConceptId):
    try:
        analysis, cache_status = fetch_person_gap_analysis_cache_aside(person_id, occupation_id, stores)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return {"analysis": analysis, "cache": cache_status}


@app.get("/api/people/{person_id}/skills")
async def list_person_skill_statements(person_id: int):
    return stores.postgres.fetch_person_skill_statements_with_labels(person_id)


@app.get("/api/people/{person_id}/skills/search")
async def search_skills_for_person(person_id: int, q: SearchText):
    query_vector = embed_texts([q])[0]
    return stores.pgvector.fetch_similar_skills_with_person_statements(query_vector, person_id, SEARCH_LIMIT)


@app.put("/api/people/{person_id}/skills/{skill_id}")
async def put_person_skill_statement(person_id: int, skill_id: ConceptId, statement: SkillStatement):
    try:
        invalidated_count = set_person_skill_statement(person_id, skill_id, statement.has_skill, stores)
    except psycopg.errors.ForeignKeyViolation as error:
        raise HTTPException(404, f"person {person_id} or skill {skill_id} does not exist") from error
    return {"invalidated_cached_analyses": invalidated_count}


@app.get("/api/db")
async def get_store_overview():
    return {
        "postgres": BROWSABLE_TABLES,
        "mongo": list(COLLECTION_VALIDATORS),
        "redis": ["analysis cache"],
        "neo4j": NODE_LABELS,
        "pgvector": ["concept_embeddings"],
        "qdrant": ["concepts"],
        "graph_counts": stores.neo4j.fetch_graph_counts(),
    }


@app.get("/api/db/{store}/{collection}")
async def browse_store(store: str, collection: str, page: Annotated[int, Query(ge=0)] = 0):
    offset = page * PAGE_SIZE
    try:
        if store == "postgres":
            records, total = stores.postgres.fetch_table_page(collection, PAGE_SIZE, offset)
        elif store == "mongo":
            records, total = stores.mongo.fetch_documents_page(collection, PAGE_SIZE, offset)
        elif store == "redis":
            records, total = stores.redis.fetch_cached_analyses_page(PAGE_SIZE, offset)
        elif store == "neo4j":
            records, total = stores.neo4j.fetch_nodes_page(collection, PAGE_SIZE, offset)
        elif store == "pgvector":
            records, total = stores.pgvector.fetch_concept_vectors_page_without_embeddings(PAGE_SIZE, offset)
        elif store == "qdrant":
            records, total = stores.qdrant.fetch_concept_payloads_page(PAGE_SIZE, offset)
        else:
            raise LookupError(f"store {store} does not exist")
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return {"records": records, "total": total, "page": page, "page_size": PAGE_SIZE}


if config.WEB_DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        if re.match(r"^api/", path):
            raise HTTPException(404)
        return FileResponse(config.WEB_DIST_DIR / "index.html")
