import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Job } from "../lib/types";
import { Alert, Spinner, StatusBadge } from "../components/ui";

const ACTIVE = new Set(["pending", "processing", "retrying"]);

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [auto, setAuto] = useState(true);

  const load = useCallback(async () => {
    try {
      const page = await api.listJobs({ limit: 50 });
      setJobs(page.items);
      setTotal(page.total);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while any job is still in flight (and auto-refresh is on).
  useEffect(() => {
    if (!auto) return;
    const hasActive = jobs.some((j) => ACTIVE.has(j.status));
    const interval = hasActive ? 2000 : 8000;
    const id = setTimeout(() => void load(), interval);
    return () => clearTimeout(id);
  }, [jobs, auto, load]);

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Ingestion Jobs</h1>
          <p className="mt-1 text-sm text-slate-500">{total} total jobs in this tenant</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-400">
          <input
            type="checkbox"
            checked={auto}
            onChange={(e) => setAuto(e.target.checked)}
            className="accent-brand-500"
          />
          Auto-refresh
        </label>
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Job</th>
              <th className="px-4 py-3 font-medium">Source</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Attempts</th>
              <th className="px-4 py-3 font-medium">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {loading && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  <Spinner /> Loading…
                </td>
              </tr>
            )}
            {!loading && jobs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  No jobs yet — ingest something on the Ingest page.
                </td>
              </tr>
            )}
            {jobs.map((j) => (
              <tr key={j.id} className="hover:bg-white/5">
                <td className="px-4 py-3 font-mono text-xs text-slate-400">{j.id.slice(0, 8)}</td>
                <td className="px-4 py-3 text-slate-300">
                  {(j.job_metadata?.title as string) ?? j.source_uri ?? "—"}
                  {j.error && <div className="mt-0.5 text-xs text-rose-400">{j.error}</div>}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={j.status} />
                </td>
                <td className="px-4 py-3 text-slate-400">
                  {j.attempts}/{j.max_attempts}
                </td>
                <td className="px-4 py-3 text-slate-500">
                  {new Date(j.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
