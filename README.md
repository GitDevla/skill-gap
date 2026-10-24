# Skill gap service

A person picks an ICT occupation they want; the service checks the occupation's essential skills (ESCO) against the
skills the person stated and returns `READY`, `GAP` (with the missing skills) or `UNKNOWN` (skills not stated yet),
plus the similar occupations the person is closest to. It uses five databases.

## Stores

| Store | Holds | Why there |
|---|---|---|
| PostgreSQL | people, their skill statements (`has_skill` true/false, no row = not stated), occupation and skill ids with labels, gap analyses with their evidence | business entities and decisions need foreign keys, CHECKs and transactions |
| MongoDB | ESCO occupation and skill documents as fetched, English and Hungarian (system of record) | the documents vary: alternative labels, scope notes, a broader occupation and translations exist only on some; `$jsonSchema` fixes the required part |
| Redis | `person:{id}:occupation:{id}:analysis`, the cached analysis with its `analysis_id` and `refreshed_at`, 1 h TTL | cache-aside read of a decision that touches every store |
| Neo4j | `Occupation-[:ESSENTIAL\|OPTIONAL]->Skill`, `Skill-[:BROADER]->Skill` | "which held skills sit below this required skill" is a variable-length path |
| pgvector, Qdrant | 965 occupation and skill descriptions (`all-MiniLM-L6-v2`, cosine) with kind, ISCO minor group, skill type | free text ("I want to protect networks") to occupations and skills |

PostgreSQL and MongoDB are the sources. Neo4j, Redis, pgvector and Qdrant are derived and carry their source id
(`source_id`; in Redis `analysis_id`) and `refreshed_at`.

## Decision

1. PostgreSQL: the person's skill statements.
2. MongoDB: the occupation's essential skills, read from the source document, not from a copy.
3. Neo4j: for each essential skill, the held skills below it in the ESCO hierarchy (`BROADER*`).
4. Each essential skill is `held` (stated yes), `lacking` (stated no), `covered` (not stated, a narrower skill is held)
   or `not_stated`. A stated no beats a held narrower skill.
5. Verdict (`gap-v1`), in this order: any `lacking` gives `GAP`; any `not_stated` gives `UNKNOWN`; otherwise `READY`.
6. Vector search proposes the 6 occupations closest to the target's description; each is judged with the same rule
   on its Neo4j edges, and the 3 with the largest share of met essential skills are shown.
7. PostgreSQL logs the analysis with its evidence; Redis caches it. Changing a skill statement deletes the person's
   cached analyses.

## Run

```sh
docker compose up -d --build
docker compose exec app python cli.py seed
```

Open http://127.0.0.1:8001. The databases keep their data in named volumes, so `seed` is needed only on the first
start. `seed` wipes every store and reloads it from `data/seed`, so rerun it any time to get back to the initial state;
`docker compose down -v` deletes the volumes. Host ports are shifted so
the stack runs next to recipe-grocery and car-diagnosis: PostgreSQL 25432, MongoDB 27019, Redis 6381, Neo4j
7476/7689 (user `neo4j`, password `skill-pass`), Qdrant 6336.

## Web UI

- Occupations: search by job title or free text (Qdrant), or pick from the list of 87
- Occupation: verdict, essential skills with their state and Have / Don't have / Not stated buttons, similar occupations
- My skills: the person's statements, each with Have / Don't have / Not stated (Not stated removes it); describe what
  you can do to find ESCO skills (pgvector, joined with the person's statements in one SQL statement)
- History: the person's analyses from the decision log
- Database: read-only pages of every PostgreSQL table, both MongoDB collections, Redis keys with remaining TTL, Neo4j
  nodes with their outgoing edges, pgvector rows and Qdrant payloads; links to the Neo4j Browser and the Qdrant
  dashboard

## CLI

`docker compose exec app python cli.py <command>`:

- `seed` - wipe every database, load `data/seed`, analyse every person against their target occupation
- `measure` - run the frozen test cases and the pgvector/Qdrant comparison; prints every number below
- `update-demo` - make an optional skill essential in one MongoDB occupation document and show the Redis, Neo4j,
  pgvector and Qdrant copies before and after the update path refreshes them
- `fetch` - download ESCO and rebuild `data/seed` (run on the host from `src/` with a venv)

## Data

- ESCO REST API (`https://ec.europa.eu/esco/api`), fetched 2026-10-20: every occupation under ISCO-08 groups 25
  (ICT professionals) and 35 (ICT technicians), 87, and every skill linked to them as essential or optional, 878.
  Labels, alternative labels and descriptions in English and Hungarian; 256 broader-skill links inside this set.
  © European Union, reuse under Commission Decision 2011/833/EU.
- Ids are slugs of the English label (`python-computer-programming`); the ESCO URI is kept in each document.
- The embedded text is the preferred label and description; alternative labels stay out, because the retrieval test
  queries are drawn from them.
- People and their statements: generated (Faker `hu_HU`, seed 42). Each person has a current occupation, most of its
  essential skills held, and a target among the 5 occupations sharing the most essential skills with it.

## Measured (`cli.py measure`)

Test cases in `data/tests/` were written before tuning. The 30 decision cases are built from the seed documents and
labelled by the rule's text, including the hierarchy cases (narrower held covers, broader held does not, stated no
beats a narrower yes). The 20 retrieval queries are ESCO alternative labels that belong to one occupation and do not
contain its preferred label.

| | Qdrant | pgvector |
|---|---|---|
| verdict accuracy, 30 cases (missing and covered skill lists exact) | 1.0 (1.0, 1.0) | 1.0 (1.0, 1.0) |
| occupation recall@5 / MRR@10, 20 queries | 0.95 / 0.91 | 0.95 / 0.91 |
| ANN recall@10, unfiltered | 1.0 | 1.0 |
| ISCO minor group 251 filter (4.6 % of rows): results, recall@10 | 10, 0.985 to 1.0 | 10, 0.995 to 1.0 |
| settings | `hnsw_ef` 64, payload indexes on concept_id, kind, isco_minor_group | `hnsw.ef_search` 40, `iterative_scan` strict_order |

The two systems share all 10 ids of their top-10 on every query. At 965 vectors both would skip HNSW by default:
Qdrant's indexing threshold is lowered and pgvector's planner is forced onto the index, so the numbers measure HNSW.
Both systems draw HNSW levels at random, so the filtered recall moves between 0.985 and 1.0 from one `seed` to the
next; within one seed it repeats. Latency differs between runs (Qdrant goes through HTTP); `measure` prints it.

## Failure cases

- Retrieval: "ICT security tester" (an ESCO alternative label of *ethical hacker*) returns *ICT system tester*, *ICT
  security administrator* and *ICT integration tester* first. The description of *ethical hacker* speaks of
  vulnerability assessments and penetration tests; "ICT ... tester" is closer to the labels and descriptions of the
  ICT tester occupations, and the embedding has no notion that a security tester is a hacker.
- Decision: the hierarchy is ESCO's, not a judgement of depth. Holding *create flowchart diagram* covers *design
  process* for an ICT network architect, because ESCO lists the first under the second. The analysis shows "via
  create flowchart diagram" so the person can see the inference and answer the skill directly.
