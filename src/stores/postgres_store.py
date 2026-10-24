from pathlib import Path
from typing import LiteralString, cast

import psycopg
from psycopg import sql
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

import config
from dataset import SEED_TABLES

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
BROWSABLE_TABLES = [*SEED_TABLES, "gap_analyses"]


class PostgresStore:
    def __init__(self, dsn: str = config.POSTGRES_DSN):
        self.conn = psycopg.Connection[DictRow].connect(dsn, row_factory=dict_row, autocommit=True)

    def reset_and_load_tables(self, tables: dict[str, list[dict]]) -> None:
        schema_sql = cast(LiteralString, SCHEMA_FILE.read_text(encoding="utf-8"))

        with self.conn.transaction():
            self.conn.execute("DROP SCHEMA public CASCADE")
            self.conn.execute("CREATE SCHEMA public")

            self.conn.execute(schema_sql)

            for table_name in SEED_TABLES:
                table_rows = tables[table_name]
                column_names = list(table_rows[0])
                copy_statement = sql.SQL("COPY {table} ({columns}) FROM STDIN").format(
                    table=sql.Identifier(table_name),
                    columns=sql.SQL(", ").join(sql.Identifier(name) for name in column_names),
                )
                with self.conn.cursor().copy(copy_statement) as copy:
                    for table_row in table_rows:
                        copy.write_row(list(table_row.values()))

            self.conn.execute("SELECT setval(pg_get_serial_sequence('people', 'id'), max(id)) FROM people")

    def fetch_people(self) -> list[DictRow]:
        return self.conn.execute(
            """
            SELECT p.id, p.name, p.city, p.current_occupation_id, c.label AS current_occupation_label,
                   p.target_occupation_id, t.label AS target_occupation_label
            FROM people p
            JOIN occupations c ON c.id = p.current_occupation_id
            JOIN occupations t ON t.id = p.target_occupation_id
            ORDER BY p.id
            """
        ).fetchall()

    def fetch_occupations(self) -> list[DictRow]:
        return self.conn.execute("SELECT id, label, isco_group FROM occupations ORDER BY label").fetchall()

    def fetch_skill_labels_by_id(self, skill_ids: list[str]) -> dict[str, str]:
        skill_rows = self.conn.execute("SELECT id, label FROM skills WHERE id = ANY(%s)", (skill_ids,)).fetchall()
        return {skill["id"]: skill["label"] for skill in skill_rows}

    def fetch_person_skill_statements(self, person_id: int) -> dict[str, bool]:
        person_row = self.conn.execute("SELECT id FROM people WHERE id = %s", (person_id,)).fetchone()

        if person_row is None:
            raise LookupError(f"person {person_id} does not exist")

        statement_rows = self.conn.execute(
            "SELECT skill_id, has_skill FROM person_skills WHERE person_id = %s", (person_id,)
        ).fetchall()
        return {statement["skill_id"]: statement["has_skill"] for statement in statement_rows}

    def fetch_person_skill_statements_with_labels(self, person_id: int) -> list[DictRow]:
        return self.conn.execute(
            """
            SELECT ps.skill_id, s.label, s.skill_type, ps.has_skill, ps.stated_at
            FROM person_skills ps JOIN skills s ON s.id = ps.skill_id
            WHERE ps.person_id = %s
            ORDER BY ps.has_skill DESC, s.label
            """,
            (person_id,),
        ).fetchall()

    def upsert_person_skill_statement(self, person_id: int, skill_id: str, has_skill: bool) -> None:
        self.conn.execute(
            """
            INSERT INTO person_skills (person_id, skill_id, has_skill) VALUES (%s, %s, %s)
            ON CONFLICT (person_id, skill_id) DO UPDATE SET has_skill = EXCLUDED.has_skill, stated_at = now()
            """,
            (person_id, skill_id, has_skill),
        )

    def remove_person_skill_statement(self, person_id: int, skill_id: str) -> None:
        self.conn.execute("DELETE FROM person_skills WHERE person_id = %s AND skill_id = %s", (person_id, skill_id))

    def add_gap_analysis(self, analysis: dict) -> int:
        analysis_row = self.conn.execute(
            """
            INSERT INTO gap_analyses (person_id, occupation_id, verdict, verdict_reason, rule_version, vector_store,
                                      evidence)
            VALUES (%(person_id)s, %(occupation_id)s, %(verdict)s, %(verdict_reason)s, %(rule_version)s,
                    %(vector_store)s, %(evidence)s)
            RETURNING id
            """,
            analysis | {"evidence": Jsonb(analysis["evidence"])},
        ).fetchone()

        assert analysis_row is not None
        return analysis_row["id"]

    def fetch_person_gap_analyses(self, person_id: int) -> list[DictRow]:
        return self.conn.execute(
            """
            SELECT g.id, g.occupation_id, o.label AS occupation_label, g.verdict, g.verdict_reason, g.decided_at
            FROM gap_analyses g JOIN occupations o ON o.id = g.occupation_id
            WHERE g.person_id = %s
            ORDER BY g.decided_at DESC, g.id DESC
            """,
            (person_id,),
        ).fetchall()

    def fetch_ready_gap_analyses(self) -> list[DictRow]:
        return self.conn.execute(
            "SELECT person_id, occupation_id FROM gap_analyses WHERE verdict = 'READY' ORDER BY id"
        ).fetchall()

    def fetch_table_page(self, table_name: str, limit: int, offset: int) -> tuple[list[DictRow], int]:
        if table_name not in BROWSABLE_TABLES:
            raise LookupError(f"table {table_name} does not exist")

        order = {"gap_analyses": "id DESC", "person_skills": "stated_at DESC"}.get(table_name, "1")
        page_query = sql.SQL("SELECT * FROM {table} ORDER BY {order} LIMIT %s OFFSET %s").format(
            table=sql.Identifier(table_name), order=sql.SQL(cast(LiteralString, order))
        )
        table_rows = self.conn.execute(page_query, (limit, offset)).fetchall()
        count_query = sql.SQL("SELECT count(*) AS n FROM {table}").format(table=sql.Identifier(table_name))
        row_count = self.conn.execute(count_query).fetchone()

        assert row_count is not None
        return table_rows, row_count["n"]
