import { useEffect, useState } from "react";
import { Link } from "react-router";

import { type HistoryRow, fetchHistory } from "../api";
import { formatTitleCase } from "../titleCase";
import { VERDICT_TEXT_CLASSES } from "../verdicts";

export default function HistoryPage({ personId }: { personId: number }) {
  const [rows, setRows] = useState<HistoryRow[] | null>(null);

  useEffect(() => {
    fetchHistory(personId).then(setRows);
  }, [personId]);

  if (rows === null) return <p className="text-stone-500">Loading…</p>;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Analysis history</h1>
      {rows.length === 0 ? (
        <p className="text-stone-500">This person has no analyses yet.</p>
      ) : (
        <table className="w-full overflow-hidden rounded-lg border border-stone-200 bg-white text-sm">
          <thead className="bg-stone-100 text-left text-stone-600">
            <tr>
              <th className="px-3 py-2">Decided</th>
              <th className="px-3 py-2">Occupation</th>
              <th className="px-3 py-2">Verdict</th>
              <th className="px-3 py-2">Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-stone-100 align-top">
                <td className="whitespace-nowrap px-3 py-2">{new Date(row.decided_at).toLocaleString("en-GB")}</td>
                <td className="px-3 py-2">
                  <Link className="text-teal-800 underline" to={`/occupations/${row.occupation_id}`}>
                    {formatTitleCase(row.occupation_label)}
                  </Link>
                </td>
                <td className={`px-3 py-2 font-medium ${VERDICT_TEXT_CLASSES[row.verdict]}`}>{row.verdict}</td>
                <td className="px-3 py-2 text-stone-600">{row.verdict_reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
