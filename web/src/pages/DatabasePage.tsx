import { useEffect, useState } from "react";

import { type StoreOverview, type StorePage, fetchStoreOverview, fetchStorePage } from "../api";

const STORE_LABELS: Record<string, string> = {
  postgres: "PostgreSQL",
  mongo: "MongoDB",
  redis: "Redis",
  neo4j: "Neo4j",
  pgvector: "pgvector",
  qdrant: "Qdrant",
};
const ADMIN_LINKS = [
  { label: "Neo4j Browser", href: "http://localhost:7476" },
  { label: "Qdrant dashboard", href: "http://localhost:6336/dashboard" },
];

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function DatabasePage() {
  const [overview, setOverview] = useState<StoreOverview | null>(null);
  const [store, setStore] = useState("postgres");
  const [collection, setCollection] = useState("gap_analyses");
  const [page, setPage] = useState(0);
  const [storePage, setStorePage] = useState<StorePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshCount, setRefreshCount] = useState(0);

  useEffect(() => {
    fetchStoreOverview().then(setOverview);
  }, [refreshCount]);

  useEffect(() => {
    setError(null);
    fetchStorePage(store, collection, page).then(setStorePage, (loadError: Error) => setError(loadError.message));
  }, [store, collection, page, refreshCount]);

  function selectStore(storeName: string) {
    if (overview === null) return;
    setStore(storeName);
    setCollection(storeName === "postgres" ? "gap_analyses" : overview[storeName][0]);
    setPage(0);
  }

  if (overview === null) return <p className="text-stone-500">Loading…</p>;

  const columns = storePage ? [...new Set(storePage.records.flatMap((record) => Object.keys(record)))] : [];
  const pageCount = storePage ? Math.max(1, Math.ceil(storePage.total / storePage.page_size)) : 1;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Database contents</h1>
        <div className="flex gap-3 text-sm">
          {ADMIN_LINKS.map((link) => (
            <a key={link.href} className="text-teal-800 underline" href={link.href} target="_blank" rel="noreferrer">
              {link.label}
            </a>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-stone-200">
        {Object.keys(STORE_LABELS).map((storeName) => (
          <button
            key={storeName}
            type="button"
            onClick={() => selectStore(storeName)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${store === storeName ? "border-teal-800 text-teal-800" : "border-transparent text-stone-600 hover:text-stone-900"}`}
          >
            {STORE_LABELS[storeName]}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        {overview[store].length > 1 && (
          <select
            className="rounded border border-stone-300 bg-white px-2 py-1"
            value={collection}
            onChange={(event) => {
              setCollection(event.target.value);
              setPage(0);
            }}
          >
            {overview[store].map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        )}
        {storePage && <span className="text-stone-600">{storePage.total} records</span>}
        {store === "neo4j" && (
          <span className="text-stone-500">
            {Object.entries(overview.graph_counts)
              .map(([name, count]) => `${name} ${count}`)
              .join(" · ")}
          </span>
        )}
        <button
          type="button"
          onClick={() => setRefreshCount((count) => count + 1)}
          className="ml-auto rounded border border-stone-300 bg-white px-3 py-1 hover:bg-stone-100"
        >
          Refresh
        </button>
      </div>

      {error && <p className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}

      {storePage && (
        <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
          <table className="w-full text-xs">
            <thead className="bg-stone-100 text-left text-stone-600">
              <tr>
                {columns.map((column) => (
                  <th key={column} className="whitespace-nowrap px-2 py-2 font-medium">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {storePage.records.map((record, index) => (
                <tr key={index} className="border-t border-stone-100 align-top">
                  {columns.map((column) => (
                    <td key={column} className="max-w-md truncate px-2 py-1.5 font-mono" title={formatCell(record[column])}>
                      {formatCell(record[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center gap-2 text-sm">
        <button
          type="button"
          disabled={page === 0}
          onClick={() => setPage((current) => current - 1)}
          className="rounded border border-stone-300 bg-white px-3 py-1 disabled:opacity-40"
        >
          Previous
        </button>
        <span>
          Page {page + 1} of {pageCount}
        </span>
        <button
          type="button"
          disabled={page + 1 >= pageCount}
          onClick={() => setPage((current) => current + 1)}
          className="rounded border border-stone-300 bg-white px-3 py-1 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
