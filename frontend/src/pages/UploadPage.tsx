import { useState } from "react";
import { api, ApiError } from "../lib/api";
import type { UploadResponse } from "../lib/types";
import { Alert, Field, Spinner } from "../components/ui";

type Tab = "text" | "file";

export default function UploadPage() {
  const [tab, setTab] = useState<Tab>("text");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res =
        tab === "text"
          ? await api.uploadText(content, title)
          : await api.uploadFile(file as File, title);
      setResult(res);
      setContent("");
      setFile(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = tab === "text" ? content.trim().length > 0 : !!file;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-100">Ingest Data</h1>
        <p className="mt-1 text-sm text-slate-500">
          Submit text or a file. It's queued, embedded by a Celery worker, and indexed for search.
        </p>
      </div>

      <div className="flex gap-1 rounded-lg bg-white/5 p-1">
        {(["text", "file"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium capitalize transition ${
              tab === t ? "bg-brand-500 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {t === "text" ? "Inline text" : "File upload"}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="card space-y-4 p-5">
        <Field label="Title (optional)">
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>

        {tab === "text" ? (
          <Field label="Content">
            <textarea
              className="input min-h-[160px] resize-y font-mono text-sm"
              placeholder="Paste the text you want to make searchable…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </Field>
        ) : (
          <Field label="File (.txt, .md, .csv, .pdf, .json — max 25 MiB)">
            <input
              className="input file:mr-3 file:rounded file:border-0 file:bg-brand-500 file:px-3 file:py-1 file:text-white"
              type="file"
              accept=".txt,.md,.csv,.pdf,.json"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Field>
        )}

        <button className="btn-primary" disabled={busy || !canSubmit}>
          {busy ? <Spinner /> : "Queue for processing"}
        </button>
      </form>

      {error && <Alert kind="error">{error}</Alert>}
      {result && (
        <Alert kind="success">
          Queued job <span className="font-mono">{result.job_id.slice(0, 8)}</span> — status{" "}
          <strong>{result.status}</strong>. Track it on the Jobs page.
        </Alert>
      )}
    </div>
  );
}
