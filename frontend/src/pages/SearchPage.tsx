import { useState } from "react";
import { api, ApiError } from "../lib/api";
import type { SearchHit, SearchMode } from "../lib/types";
import { Alert, Field, Spinner } from "../components/ui";

const MODES: SearchMode[] = ["hybrid", "semantic", "keyword"];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [topK, setTopK] = useState(5);
  const [alpha, setAlpha] = useState(0.5);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tookMs, setTookMs] = useState<number | null>(null);

  async function onSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    const t0 = performance.now();
    try {
      const res = await api.search(query, mode, topK, alpha);
      setHits(res.hits);
      setTookMs(Math.round(performance.now() - t0));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed");
      setHits(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-100">Semantic Search</h1>
        <p className="mt-1 text-sm text-slate-500">
          Query your ingested knowledge base with vector, keyword, or hybrid retrieval.
        </p>
      </div>

      <form onSubmit={onSearch} className="card space-y-4 p-5">
        <div className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="Ask anything about your data…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="btn-primary" disabled={busy}>
            {busy ? <Spinner /> : "Search"}
          </button>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field label="Mode">
            <select className="input" value={mode} onChange={(e) => setMode(e.target.value as SearchMode)}>
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
          <Field label={`Top K — ${topK}`}>
            <input
              type="range"
              min={1}
              max={20}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              className="w-full accent-brand-500"
            />
          </Field>
          <Field label={`Hybrid α (vector↔keyword) — ${alpha.toFixed(2)}`}>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={alpha}
              disabled={mode !== "hybrid"}
              onChange={(e) => setAlpha(Number(e.target.value))}
              className="w-full accent-brand-500 disabled:opacity-40"
            />
          </Field>
        </div>
      </form>

      {error && <Alert kind="error">{error}</Alert>}

      {hits && (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm text-slate-500">
            <span>
              {hits.length} result{hits.length === 1 ? "" : "s"}
            </span>
            {tookMs !== null && <span>{tookMs} ms</span>}
          </div>
          {hits.length === 0 && (
            <Alert kind="info">No matches. Try ingesting documents first, or broaden your query.</Alert>
          )}
          {hits.map((h) => (
            <div key={h.chunk_id} className="card p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-mono text-xs text-slate-500">
                  {(h.metadata?.title as string) ?? h.document_id.slice(0, 8)}
                </span>
                <span className="rounded-full bg-brand-500/15 px-2 py-0.5 text-xs font-medium text-brand-400">
                  {h.score.toFixed(3)}
                </span>
              </div>
              <p className="text-sm leading-relaxed text-slate-300">{h.content}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
