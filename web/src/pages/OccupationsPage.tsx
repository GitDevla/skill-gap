import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router";

import { type OccupationSummary, type Person, type SimilarOccupation, fetchOccupations, searchOccupations } from "../api";
import { formatTitleCase } from "../titleCase";

export default function OccupationsPage({ person }: { person: Person | null }) {
  const [occupations, setOccupations] = useState<OccupationSummary[]>([]);
  const [text, setText] = useState("");
  const [results, setResults] = useState<SimilarOccupation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchOccupations().then(setOccupations);
  }, []);

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      setResults(await searchOccupations(text));
    } catch (searchError) {
      setError((searchError as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Occupations</h1>

      {person && (
        <p className="text-sm text-stone-600">
          {person.name} works as <span className="font-medium">{formatTitleCase(person.current_occupation_label)}</span> and wants to
          become{" "}
          <Link className="font-medium text-teal-800 underline" to={`/occupations/${person.target_occupation_id}`}>
            {formatTitleCase(person.target_occupation_label)}
          </Link>
          .
        </p>
      )}

      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          className="w-full rounded border border-stone-300 bg-white px-3 py-2"
          placeholder="A job title or what you want to do, e.g. 'I want to protect company networks from attacks'"
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
          <h2 className="text-lg font-semibold">Closest occupations (Qdrant)</h2>
          <ol className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white">
            {results.map((result) => (
              <li key={result.concept_id} className="flex items-center justify-between px-4 py-2">
                <Link className="text-teal-800 underline" to={`/occupations/${result.concept_id}`}>
                  {formatTitleCase(result.label)}
                </Link>
                <span className="font-mono text-xs text-stone-500">{result.score.toFixed(3)}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">All {occupations.length} ICT occupations</h2>
        <ul className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {occupations.map((occupation) => (
            <li key={occupation.id}>
              <Link className="text-teal-800 hover:underline" to={`/occupations/${occupation.id}`}>
                {formatTitleCase(occupation.label)}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
