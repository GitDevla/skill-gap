from datetime import UTC, datetime

from pymongo import ASCENDING, MongoClient, ReturnDocument

import config

CONCEPT_ID = {"bsonType": "string", "pattern": "^[a-z0-9-]+$"}
CONCEPT_IDS = {"bsonType": "array", "items": CONCEPT_ID, "uniqueItems": True}
NON_EMPTY_STRING = {"bsonType": "string", "minLength": 1}
LANGUAGE_TEXT = {
    "bsonType": "object",
    "required": ["en"],
    "additionalProperties": False,
    "properties": {"en": NON_EMPTY_STRING, "hu": NON_EMPTY_STRING},
}
LANGUAGE_LABELS = {
    "bsonType": "object",
    "additionalProperties": False,
    "properties": {
        language: {"bsonType": "array", "items": NON_EMPTY_STRING, "minItems": 1} for language in ["en", "hu"]
    },
}
COMMON_PROPERTIES = {
    "_id": CONCEPT_ID,
    "esco_uri": {"bsonType": "string", "pattern": "^http://data\\.europa\\.eu/esco/"},
    "preferred_label": LANGUAGE_TEXT,
    "alternative_labels": LANGUAGE_LABELS,
    "description": LANGUAGE_TEXT,
    "scope_note": LANGUAGE_TEXT,
    "fetched_on": {"bsonType": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
    "updated_at": {"bsonType": "date"},
}
COMMON_REQUIRED = ["_id", "esco_uri", "preferred_label", "description", "fetched_on"]
OCCUPATION_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [*COMMON_REQUIRED, "esco_code", "isco_group", "essential_skill_ids", "optional_skill_ids"],
        "properties": COMMON_PROPERTIES
        | {
            "esco_code": {"bsonType": "string", "pattern": "^[0-9]{4}(\\.[0-9]+)+$"},
            "isco_group": {"bsonType": "string", "pattern": "^[0-9]{4}$"},
            "essential_skill_ids": CONCEPT_IDS | {"minItems": 1},
            "optional_skill_ids": CONCEPT_IDS,
            "broader_occupation_id": CONCEPT_ID,
        },
    }
}
SKILL_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [*COMMON_REQUIRED, "skill_type", "reuse_level", "broader_skill_ids"],
        "properties": COMMON_PROPERTIES
        | {
            "skill_type": {"enum": ["skill", "knowledge"]},
            "reuse_level": {"enum": ["transversal", "cross-sector", "sector-specific", "occupation-specific"]},
            "broader_skill_ids": CONCEPT_IDS,
        },
    }
}
COLLECTION_VALIDATORS = {"occupations": OCCUPATION_VALIDATOR, "skills": SKILL_VALIDATOR}


class MongoStore:
    def __init__(self, uri: str = config.MONGO_URI, database: str = config.MONGO_DB):
        self.db = MongoClient(uri, tz_aware=True)[database]
        self.occupations = self.db["occupations"]
        self.skills = self.db["skills"]

    def reset_and_load_esco_documents(self, occupation_documents: list[dict], skill_documents: list[dict]) -> None:
        for collection_name, validator in COLLECTION_VALIDATORS.items():
            self.db.drop_collection(collection_name)
            self.db.create_collection(
                collection_name, validator=validator, validationLevel="strict", validationAction="error"
            )

        self.occupations.create_index([("isco_group", ASCENDING)])
        self.skills.create_index([("broader_skill_ids", ASCENDING)])

        self.occupations.insert_many(occupation_documents)
        self.skills.insert_many(skill_documents)

    def fetch_occupation(self, occupation_id: str) -> dict:
        occupation = self.occupations.find_one({"_id": occupation_id})

        if occupation is None:
            raise LookupError(f"occupation {occupation_id} does not exist")
        return occupation

    def update_occupation_fields(self, occupation_id: str, fields: dict) -> dict:
        updated_fields = fields | {"updated_at": datetime.now(UTC)}

        occupation = self.occupations.find_one_and_update(
            {"_id": occupation_id}, {"$set": updated_fields}, return_document=ReturnDocument.AFTER
        )

        if occupation is None:
            raise LookupError(f"occupation {occupation_id} does not exist")
        return occupation

    def fetch_documents_page(self, collection_name: str, limit: int, offset: int) -> tuple[list[dict], int]:
        if collection_name not in COLLECTION_VALIDATORS:
            raise LookupError(f"collection {collection_name} does not exist")

        collection = self.db[collection_name]
        sort_order = [("updated_at", -1), ("_id", ASCENDING)]
        documents = list(collection.find().sort(sort_order).skip(offset).limit(limit))
        return documents, collection.count_documents({})
