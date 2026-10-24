from datetime import datetime
from typing import LiteralString, cast

from neo4j import GraphDatabase, ManagedTransaction

import config

CONSTRAINTS: list[LiteralString] = [
    "CREATE CONSTRAINT occupation_id IF NOT EXISTS FOR (o:Occupation) REQUIRE o.id IS UNIQUE",
    "CREATE CONSTRAINT skill_id IF NOT EXISTS FOR (s:Skill) REQUIRE s.id IS UNIQUE",
]
REQUIRED = {
    "occupations": {
        "id": str,
        "label": str,
        "isco_group": str,
        "essential_skill_ids": list,
        "optional_skill_ids": list,
    },
    "skills": {"id": str, "label": str, "skill_type": str, "broader_skill_ids": list},
}
NODE_LABELS = ["Occupation", "Skill"]
LOAD_STATEMENTS: list[LiteralString] = [
    """UNWIND $skills AS row
       CREATE (:Skill {id: row.id, label: row.label, skill_type: row.skill_type, source_id: row.id,
                       refreshed_at: $now})""",
    """UNWIND $occupations AS row
       CREATE (:Occupation {id: row.id, label: row.label, isco_group: row.isco_group, source_id: row.id,
                            refreshed_at: $now})""",
    """UNWIND $skills AS row
       UNWIND row.broader_skill_ids AS broader_id
       MATCH (narrower:Skill {id: row.id}), (broader:Skill {id: broader_id})
       CREATE (narrower)-[:BROADER]->(broader)""",
    """UNWIND $occupations AS row
       UNWIND row.essential_skill_ids AS skill_id
       MATCH (o:Occupation {id: row.id}), (s:Skill {id: skill_id})
       CREATE (o)-[:ESSENTIAL]->(s)""",
    """UNWIND $occupations AS row
       UNWIND row.optional_skill_ids AS skill_id
       MATCH (o:Occupation {id: row.id}), (s:Skill {id: skill_id})
       CREATE (o)-[:OPTIONAL]->(s)""",
]
REFRESH_OCCUPATION_STATEMENTS: list[LiteralString] = [
    """MATCH (o:Occupation {id: $id})
       SET o.label = $label, o.isco_group = $isco_group, o.refreshed_at = $now
       WITH o
       MATCH (o)-[r:ESSENTIAL|OPTIONAL]->()
       DELETE r""",
    """MATCH (o:Occupation {id: $id})
       UNWIND $essential_skill_ids AS skill_id
       MATCH (s:Skill {id: skill_id})
       CREATE (o)-[:ESSENTIAL]->(s)""",
    """MATCH (o:Occupation {id: $id})
       UNWIND $optional_skill_ids AS skill_id
       MATCH (s:Skill {id: skill_id})
       CREATE (o)-[:OPTIONAL]->(s)""",
]


def _run_statements(transaction: ManagedTransaction, statements: list[LiteralString], parameters: dict) -> None:
    for statement in statements:
        transaction.run(statement, parameters).consume()


def build_graph_source_rows(occupation_documents: list[dict], skill_documents: list[dict]) -> dict[str, list]:
    occupations = [
        {
            "id": occupation["_id"],
            "label": occupation["preferred_label"]["en"],
            "isco_group": occupation["isco_group"],
            "essential_skill_ids": occupation["essential_skill_ids"],
            "optional_skill_ids": occupation["optional_skill_ids"],
        }
        for occupation in occupation_documents
    ]
    skills = [
        {
            "id": skill["_id"],
            "label": skill["preferred_label"]["en"],
            "skill_type": skill["skill_type"],
            "broader_skill_ids": skill["broader_skill_ids"],
        }
        for skill in skill_documents
    ]
    return {"occupations": occupations, "skills": skills}


class Neo4jStore:
    def __init__(
        self, uri: str = config.NEO4J_URI, user: str = config.NEO4J_USER, password: str = config.NEO4J_PASSWORD
    ):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def reset_and_load_graph(self, source_rows: dict[str, list], refreshed_at: datetime) -> None:
        for source_name, required_fields in REQUIRED.items():
            for source_row in source_rows[source_name]:
                for field_name, field_type in required_fields.items():
                    value = source_row.get(field_name)
                    if not isinstance(value, field_type) or value == "":
                        raise ValueError(f"{source_name}: {field_name} must be a non-empty {field_type.__name__}")

        self.driver.execute_query("MATCH (n) DETACH DELETE n")

        for constraint in CONSTRAINTS:
            self.driver.execute_query(constraint)

        load_parameters: dict[str, object] = dict(source_rows)
        load_parameters["now"] = refreshed_at
        with self.driver.session() as session:
            session.execute_write(_run_statements, LOAD_STATEMENTS, load_parameters)

    def fetch_held_narrower_skill_ids(self, required_skill_ids: list[str], held_skill_ids: list[str]) -> dict:
        skill_records, _, _ = self.driver.execute_query(
            """
            UNWIND $required_skill_ids AS skill_id
            OPTIONAL MATCH (narrower:Skill)-[:BROADER*1..]->(:Skill {id: skill_id})
            WHERE narrower.id IN $held_skill_ids
            RETURN skill_id, collect(DISTINCT narrower.id) AS narrower_held_skill_ids
            """,
            required_skill_ids=required_skill_ids,
            held_skill_ids=held_skill_ids,
        )
        return {record["skill_id"]: sorted(record["narrower_held_skill_ids"]) for record in skill_records}

    def fetch_occupations_essential_skill_ids(self, occupation_ids: list[str]) -> dict[str, dict]:
        occupation_records, _, _ = self.driver.execute_query(
            """
            MATCH (o:Occupation) WHERE o.id IN $occupation_ids
            OPTIONAL MATCH (o)-[:ESSENTIAL]->(s:Skill)
            RETURN o.id AS occupation_id, o.label AS label, o.refreshed_at AS refreshed_at,
                   collect(s.id) AS essential_skill_ids
            """,
            occupation_ids=occupation_ids,
        )

        occupations = {}
        for record in occupation_records:
            occupations[record["occupation_id"]] = {
                "label": record["label"],
                "refreshed_at": record["refreshed_at"].iso_format(),
                "essential_skill_ids": sorted(record["essential_skill_ids"]),
            }
        return occupations

    def refresh_occupation(self, occupation: dict, refreshed_at: datetime) -> None:
        refresh_parameters = {
            "id": occupation["_id"],
            "label": occupation["preferred_label"]["en"],
            "isco_group": occupation["isco_group"],
            "essential_skill_ids": occupation["essential_skill_ids"],
            "optional_skill_ids": occupation["optional_skill_ids"],
            "now": refreshed_at,
        }

        with self.driver.session() as session:
            session.execute_write(_run_statements, REFRESH_OCCUPATION_STATEMENTS, refresh_parameters)

    def fetch_graph_counts(self) -> dict[str, int]:
        count_records, _, _ = self.driver.execute_query(
            """
            CALL () { MATCH (n) RETURN labels(n)[0] AS name, count(*) AS n
                      UNION ALL
                      MATCH ()-[r]->() RETURN type(r) AS name, count(*) AS n }
            RETURN name, n ORDER BY name
            """
        )
        return {record["name"]: record["n"] for record in count_records}

    def fetch_nodes_page(self, label: str, limit: int, offset: int) -> tuple[list[dict], int]:
        if label not in NODE_LABELS:
            raise LookupError(f"label {label} does not exist")

        label = cast(LiteralString, label)
        node_records, _, _ = self.driver.execute_query(
            f"""
            MATCH (n:{label})
            OPTIONAL MATCH (n)-[r]->(other)
            WITH n, collect(type(r) + ' ' + other.id) AS outgoing_edges
            RETURN n {{.*}} AS node, outgoing_edges
            ORDER BY n.id SKIP $offset LIMIT $limit
            """,
            offset=offset,
            limit=limit,
        )
        count_records, _, _ = self.driver.execute_query(f"MATCH (n:{label}) RETURN count(n) AS n")

        nodes = []
        for record in node_records:
            node = {
                key: value.iso_format() if hasattr(value, "iso_format") else value
                for key, value in record["node"].items()
            }
            nodes.append(node | {"outgoing_edges": record["outgoing_edges"]})
        return nodes, count_records[0]["n"]
