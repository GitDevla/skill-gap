import { type FormEvent, useEffect, useState } from "react";

import {
  type HasSkill,
  type SkillSearchResult,
  type SkillStatement,
  fetchSkillStatements,
  saveSkillStatement,
  searchSkills,
} from "../api";
import SkillStatementToggle from "../components/SkillStatementToggle";
import { formatTitleCase } from "../titleCase";

export default function SkillsPage({ personId }: { personId: number }) {
  const [statements, setStatements] = useState<SkillStatement[] | null>(null);
  const [text, setText] = useState("");
  const [results, setResults] = useState<SkillSearchResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setResults(null);
    fetchSkillStatements(personId).then(setStatements);
  }, [personId]);

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      setResults(await searchSkills(personId, text));
    } catch (searchError) {
      setError((searchError as Error).message);
    }
  }

  async function changeStatement(skillId: string, hasSkill: HasSkill) {
    setSaving(true);
    setError(null);
    try {
      await saveSkillStatement(personId, skillId, hasSkill);
      setStatements(await fetchSkillStatements(personId));
      setResults((current) =>
        current?.map((result) => (result.skill_id === skillId ? { ...result, has_skill: hasSkill } : result)) ?? null,
      );
    } catch (saveError) {
      setError((saveError as Error).message);
    }
    setSaving(false);
  }

  if (statements === null) return <p className="text-stone-500">Loading…</p>;

  const heldCount = statements.filter((statement) => statement.has_skill).length;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">My skills</h1>

      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          className="w-full rounded border border-stone-300 bg-white px-3 py-2"
          placeholder="Describe what you can do, e.g. 'I write SQL queries and tune slow databases'"
          value={text}
          minLength={2}
          maxLength={300}
          required
          onChange={(event) => setText(event.target.value)}
        />
        <button type="submit" className="rounded bg-teal-800 px-4 py-2 text-sm font-medium text-white hover:bg-teal-900">
          Search
        </button>
      </form>
      {error && <p className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}

      {results && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Matching ESCO skills (pgvector)</h2>
          <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white">
            {results.map((result) => (
              <li key={result.skill_id} className="flex items-center justify-between gap-3 px-4 py-2">
                <span className="text-sm">
                  {formatTitleCase(result.label)} <span className="text-xs text-stone-500">{result.skill_type}</span>
                </span>
                <span className="ml-auto font-mono text-xs text-stone-500">{result.score.toFixed(3)}</span>
                <SkillStatementToggle
                  value={result.has_skill}
                  disabled={saving}
                  onChange={(hasSkill) => changeStatement(result.skill_id, hasSkill)}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">
          Stated skills ({heldCount} held, {statements.length - heldCount} missing)
        </h2>
        {statements.length === 0 ? (
          <p className="text-stone-500">No skill stated yet.</p>
        ) : (
          <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white">
            {statements.map((statement) => (
              <li key={statement.skill_id} className="flex items-center justify-between gap-3 px-4 py-2">
                <span className="text-sm">
                  {formatTitleCase(statement.label)} <span className="text-xs text-stone-500">{statement.skill_type}</span>
                </span>
                <SkillStatementToggle
                  value={statement.has_skill}
                  disabled={saving}
                  onChange={(hasSkill) => changeStatement(statement.skill_id, hasSkill)}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
