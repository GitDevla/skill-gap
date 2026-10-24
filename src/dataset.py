import csv
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

from faker import Faker

import config

SEED = 42
ESCO_API = "https://ec.europa.eu/esco/api/resource/"
HTTP_HEADERS = {"User-Agent": "skill-gap-coursework/1.0"}
ISCO_ROOT_GROUPS = ["C25", "C35"]
FETCH_WORKERS = 2
FETCH_PAUSE_SECONDS = 0.2
FETCH_ATTEMPTS = 4
RAW_OCCUPATIONS_FILE = config.RAW_DIR / "esco_occupations.jsonl"
RAW_SKILLS_FILE = config.RAW_DIR / "esco_skills.jsonl"
RAW_MANIFEST_FILE = config.RAW_DIR / "manifest.json"
KEPT_LANGUAGES = ["en", "hu"]
SEED_TABLES = ["occupations", "skills", "people", "person_skills"]
PERSON_COUNT = 200
TARGET_CANDIDATE_COUNT = 5
READY_PERSON_SHARE = 0.15
CURRENT_ESSENTIAL_HELD_SHARE = 0.85
CURRENT_OPTIONAL_HELD_SHARE = 0.1
TARGET_SKILL_HELD_SHARE = 0.4
TARGET_SKILL_LACKING_SHARE = 0.2
STATEMENTS_START = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)
STATEMENTS_SPAN_MINUTES = 300_000

rng = random.Random()
fake = Faker("hu_HU")


def download_raw_esco() -> None:
    occupation_isco_groups = {}
    for root_group in ISCO_ROOT_GROUPS:
        occupation_isco_groups |= _fetch_isco_group_occupation_uris(f"http://data.europa.eu/esco/isco/{root_group}")

    occupation_documents = []
    pending_uris = list(occupation_isco_groups)
    while pending_uris:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            fetched_documents = list(pool.map(lambda uri: _fetch_esco_resource("occupation", uri), pending_uris))
        pending_uris = []
        for occupation in fetched_documents:
            occupation["isco_group"] = occupation_isco_groups[occupation["uri"]]
            occupation_documents.append(occupation)
            for narrower in occupation["_links"].get("narrowerOccupation", []):
                if narrower["uri"] not in occupation_isco_groups:
                    occupation_isco_groups[narrower["uri"]] = occupation["isco_group"]
                    pending_uris.append(narrower["uri"])

    skill_uris = sorted(
        {
            skill["uri"]
            for occupation in occupation_documents
            for relation in ["hasEssentialSkill", "hasOptionalSkill"]
            for skill in occupation["_links"].get(relation, [])
        }
    )
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        skill_documents = list(pool.map(lambda uri: _fetch_esco_resource("skill", uri), skill_uris))

    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(RAW_OCCUPATIONS_FILE, occupation_documents)
    write_jsonl(RAW_SKILLS_FILE, skill_documents)
    raw_manifest = {"source": ESCO_API, "isco_root_groups": ISCO_ROOT_GROUPS, "fetched_on": date.today().isoformat()}
    RAW_MANIFEST_FILE.write_text(json.dumps(raw_manifest, indent=2) + "\n", encoding="utf-8")


def _fetch_isco_group_occupation_uris(isco_uri: str) -> dict[str, str]:
    isco_group = _fetch_esco_resource("concept", isco_uri)

    occupation_isco_groups = {}
    for occupation in isco_group["_links"].get("narrowerOccupation", []):
        occupation_isco_groups[occupation["uri"]] = isco_group["code"]
    for narrower_group in isco_group["_links"].get("narrowerConcept", []):
        occupation_isco_groups |= _fetch_isco_group_occupation_uris(narrower_group["uri"])
    return occupation_isco_groups


def _fetch_esco_resource(kind: str, uri: str) -> dict:
    query = urllib.parse.urlencode({"uri": uri, "language": "en"})
    request = urllib.request.Request(f"{ESCO_API}{kind}?{query}", headers=HTTP_HEADERS)

    for attempt in range(FETCH_ATTEMPTS):
        time.sleep(FETCH_PAUSE_SECONDS * 2**attempt)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if (error.code != 429 and error.code < 500) or attempt == FETCH_ATTEMPTS - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == FETCH_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def build_seed_files() -> dict[str, int]:
    rng.seed(SEED)
    Faker.seed(SEED)
    raw_occupations = read_jsonl(RAW_OCCUPATIONS_FILE)
    raw_skills = read_jsonl(RAW_SKILLS_FILE)
    raw_manifest = json.loads(RAW_MANIFEST_FILE.read_text(encoding="utf-8"))

    concept_ids = {}
    for raw_concept in [*raw_occupations, *raw_skills]:
        concept_id = build_concept_id(raw_concept["preferredLabel"]["en"])
        if concept_id in concept_ids.values():
            raise ValueError(f"two ESCO concepts map to the id {concept_id}")
        concept_ids[raw_concept["uri"]] = concept_id
    fetched_on = raw_manifest["fetched_on"]
    occupation_documents = sorted(
        (_build_occupation_document(occupation, concept_ids, fetched_on) for occupation in raw_occupations),
        key=lambda occupation: occupation["_id"],
    )
    skill_documents = sorted(
        (_build_skill_document(skill, concept_ids, fetched_on) for skill in raw_skills),
        key=lambda skill: skill["_id"],
    )

    occupations_by_id = {occupation["_id"]: occupation for occupation in occupation_documents}
    target_candidates = _find_target_candidates(occupation_documents)
    person_rows, statement_rows = [], []
    for person_id in range(1, PERSON_COUNT + 1):
        person = _generate_random_person(person_id, list(occupations_by_id), target_candidates)
        person_rows.append(person)
        statement_rows.extend(_generate_random_skill_statements(person, occupations_by_id))

    row_counts = {
        "occupations": len(occupation_documents),
        "skills": len(skill_documents),
        "people": len(person_rows),
        "person_skills": len(statement_rows),
    }
    manifest = {
        "source": "ESCO REST API " + ESCO_API,
        "isco_root_groups": ISCO_ROOT_GROUPS,
        "fetched_on": fetched_on,
        "languages": KEPT_LANGUAGES,
        "seed": SEED,
        "counts": row_counts,
    }
    config.SEED_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.SEED_DIR / "occupations.jsonl", occupation_documents)
    write_jsonl(config.SEED_DIR / "skills.jsonl", skill_documents)
    _write_csv(config.SEED_DIR / "people.csv", person_rows)
    _write_csv(config.SEED_DIR / "person_skills.csv", statement_rows)
    (config.SEED_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return row_counts


def build_concept_id(label: str) -> str:
    spelled_label = label.lower().replace("++", " plus plus").replace("#", " sharp")
    return re.sub(r"[^a-z0-9]+", "-", spelled_label).strip("-")


def _build_occupation_document(raw_occupation: dict, concept_ids: dict[str, str], fetched_on: str) -> dict:
    links = raw_occupation["_links"]
    occupation = {
        "_id": concept_ids[raw_occupation["uri"]],
        "esco_uri": raw_occupation["uri"],
        "esco_code": raw_occupation["code"],
        "isco_group": raw_occupation["isco_group"],
        **_build_text_fields(raw_occupation),
        "essential_skill_ids": sorted(concept_ids[skill["uri"]] for skill in links.get("hasEssentialSkill", [])),
        "optional_skill_ids": sorted(concept_ids[skill["uri"]] for skill in links.get("hasOptionalSkill", [])),
        "fetched_on": fetched_on,
    }

    broader_ids = [
        concept_ids[parent["uri"]] for parent in links.get("broaderOccupation", []) if parent["uri"] in concept_ids
    ]
    if broader_ids:
        occupation["broader_occupation_id"] = broader_ids[0]
    return occupation


def _build_skill_document(raw_skill: dict, concept_ids: dict[str, str], fetched_on: str) -> dict:
    links = raw_skill["_links"]
    return {
        "_id": concept_ids[raw_skill["uri"]],
        "esco_uri": raw_skill["uri"],
        "skill_type": links["hasSkillType"][0]["uri"].rsplit("/", 1)[1],
        "reuse_level": links["hasReuseLevel"][0]["uri"].rsplit("/", 1)[1],
        **_build_text_fields(raw_skill),
        "broader_skill_ids": sorted(
            concept_ids[broader["uri"]] for broader in links.get("broaderSkill", []) if broader["uri"] in concept_ids
        ),
        "fetched_on": fetched_on,
    }


def _build_text_fields(raw_concept: dict) -> dict:
    text_fields = {"preferred_label": _keep_languages(raw_concept["preferredLabel"])}

    alternative_labels = _keep_languages(raw_concept.get("alternativeLabel") or {})
    if alternative_labels:
        text_fields["alternative_labels"] = alternative_labels
    for raw_name, name in [("description", "description"), ("scopeNote", "scope_note")]:
        literals = {language: text["literal"].strip() for language, text in (raw_concept.get(raw_name) or {}).items()}
        kept_literals = _keep_languages(literals)
        if kept_literals:
            text_fields[name] = kept_literals
    return text_fields


def _keep_languages(values_by_language: dict) -> dict:
    return {language: values_by_language[language] for language in KEPT_LANGUAGES if language in values_by_language}


def _find_target_candidates(occupation_documents: list[dict]) -> dict[str, list[str]]:
    essential_sets = {occupation["_id"]: set(occupation["essential_skill_ids"]) for occupation in occupation_documents}

    target_candidates = {}
    for occupation_id, essential_ids in essential_sets.items():
        overlaps = []
        for other_id, other_essential_ids in essential_sets.items():
            if other_id != occupation_id:
                jaccard = len(essential_ids & other_essential_ids) / len(essential_ids | other_essential_ids)
                overlaps.append((-jaccard, other_id))
        target_candidates[occupation_id] = [other_id for _, other_id in sorted(overlaps)[:TARGET_CANDIDATE_COUNT]]
    return target_candidates


def _generate_random_person(person_id: int, occupation_ids: list[str], target_candidates: dict) -> dict:
    current_occupation_id = rng.choice(occupation_ids)
    target_occupation_id = rng.choice(target_candidates[current_occupation_id])
    name = fake.name()
    email = f"{fake.user_name()}{person_id}@example.com"
    return {
        "id": person_id,
        "name": name,
        "email": email,
        "city": fake.city(),
        "current_occupation_id": current_occupation_id,
        "target_occupation_id": target_occupation_id,
    }


def _generate_random_skill_statements(person: dict, occupations_by_id: dict[str, dict]) -> list[dict]:
    current_occupation = occupations_by_id[person["current_occupation_id"]]
    target_occupation = occupations_by_id[person["target_occupation_id"]]
    is_ready = rng.random() < READY_PERSON_SHARE

    has_skill_by_id = {}
    for skill_id in current_occupation["essential_skill_ids"]:
        if rng.random() < CURRENT_ESSENTIAL_HELD_SHARE:
            has_skill_by_id[skill_id] = True
    for skill_id in current_occupation["optional_skill_ids"]:
        if rng.random() < CURRENT_OPTIONAL_HELD_SHARE:
            has_skill_by_id[skill_id] = True
    for skill_id in target_occupation["essential_skill_ids"]:
        draw = rng.random()
        if skill_id in has_skill_by_id:
            continue
        if is_ready or draw < TARGET_SKILL_HELD_SHARE:
            has_skill_by_id[skill_id] = True
        elif draw < TARGET_SKILL_HELD_SHARE + TARGET_SKILL_LACKING_SHARE:
            has_skill_by_id[skill_id] = False

    statement_rows = []
    for skill_id, has_skill in sorted(has_skill_by_id.items()):
        stated_at = STATEMENTS_START + timedelta(minutes=rng.randint(0, STATEMENTS_SPAN_MINUTES))
        statement_rows.append(
            {
                "person_id": person["id"],
                "skill_id": skill_id,
                "has_skill": has_skill,
                "stated_at": stated_at.isoformat(),
            }
        )
    return statement_rows


def read_seed_files() -> tuple[dict[str, list[dict]], list[dict], list[dict]]:
    occupation_documents = read_jsonl(config.SEED_DIR / "occupations.jsonl")
    skill_documents = read_jsonl(config.SEED_DIR / "skills.jsonl")

    tables = {
        "occupations": [
            {
                "id": occupation["_id"],
                "label": occupation["preferred_label"]["en"],
                "isco_group": occupation["isco_group"],
            }
            for occupation in occupation_documents
        ],
        "skills": [
            {"id": skill["_id"], "label": skill["preferred_label"]["en"], "skill_type": skill["skill_type"]}
            for skill in skill_documents
        ],
    }
    for table_name in ["people", "person_skills"]:
        with open(config.SEED_DIR / f"{table_name}.csv", newline="", encoding="utf-8") as seed_file:
            tables[table_name] = list(csv.DictReader(seed_file))
    return tables, occupation_documents, skill_documents


def _write_csv(path, table_rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(table_rows[0]))
        writer.writeheader()
        writer.writerows(table_rows)


def read_jsonl(path) -> list[dict]:
    documents = []
    with open(path, encoding="utf-8") as jsonl_file:
        for json_line in jsonl_file:
            documents.append(json.loads(json_line))
    return documents


def write_jsonl(path, documents: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as jsonl_file:
        for document in documents:
            jsonl_file.write(json.dumps(document, ensure_ascii=False) + "\n")
