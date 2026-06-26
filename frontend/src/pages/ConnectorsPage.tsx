import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Connector, ConnectorType } from "../lib/types";
import { Alert, Field, Spinner } from "../components/ui";

const TYPES: ConnectorType[] = ["postgres", "mariadb", "mysql", "rest", "s3", "csv", "pdf"];

// Starter config templates so users see the expected shape for each source type.
const TEMPLATES: Record<ConnectorType, Record<string, unknown>> = {
  postgres: {
    dsn: "postgresql+asyncpg://user:pass@host.docker.internal:5432/mydb",
    table: "orders",
    id_field: "id",
    cursor_field: "updated_at",
    content_fields: ["title", "description"],
    batch_size: 500,
  },
  mariadb: {
    dsn: "mariadb://user:pass@host.docker.internal:3306/mydb",
    _hint: "Omit 'table' to sync ALL tables. Or set a single table + cursor_field.",
    exclude_tables: [],
    batch_size: 500,
  },
  mysql: {
    dsn: "mysql://user:pass@host.docker.internal:3306/mydb",
    _hint: "Omit 'table' to sync ALL tables. Or set a single table + cursor_field.",
    exclude_tables: [],
    batch_size: 500,
  },
  rest: {
    url: "https://api.example.com/v1/items",
    method: "GET",
    headers: {},
    records_path: "data",
    rate_limit_per_sec: 10,
  },
  s3: {
    bucket: "my-bucket",
    prefix: "docs/",
    region: "us-east-1",
  },
  csv: { note: "CSV is usually uploaded on the Ingest page; connector form pulls from a URL", url: "" },
  pdf: { note: "PDF is usually uploaded on the Ingest page", url: "" },
};

interface RowState {
  validating?: boolean;
  syncing?: boolean;
  message?: { kind: "error" | "success" | "info"; text: string };
}

export default function ConnectorsPage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rowState, setRowState] = useState<Record<string, RowState>>({});

  const [name, setName] = useState("");
  const [type, setType] = useState<ConnectorType>("postgres");
  const [configText, setConfigText] = useState(JSON.stringify(TEMPLATES.postgres, null, 2));
  const [creating, setCreating] = useState(false);
  const [formMsg, setFormMsg] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const page = await api.listConnectors();
      setConnectors(page.items);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load connectors");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function onTypeChange(t: ConnectorType) {
    setType(t);
    setConfigText(JSON.stringify(TEMPLATES[t], null, 2));
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormMsg(null);
    let config: Record<string, unknown>;
    try {
      config = JSON.parse(configText);
    } catch {
      setFormMsg({ kind: "error", text: "Config is not valid JSON" });
      return;
    }
    setCreating(true);
    try {
      await api.createConnector(name, type, config);
      setFormMsg({ kind: "success", text: `Connector "${name}" created` });
      setName("");
      await load();
    } catch (err) {
      setFormMsg({ kind: "error", text: err instanceof ApiError ? err.message : "Create failed" });
    } finally {
      setCreating(false);
    }
  }

  function patchRow(id: string, patch: RowState) {
    setRowState((s) => ({ ...s, [id]: { ...s[id], ...patch } }));
  }

  async function onValidate(id: string) {
    patchRow(id, { validating: true, message: undefined });
    try {
      const res = await api.validateConnector(id);
      patchRow(id, {
        validating: false,
        message: {
          kind: res.ok ? "success" : "error",
          text: res.ok ? `Valid — ${res.detail ?? "ok"}` : `Invalid — ${res.detail ?? "failed"}`,
        },
      });
    } catch (err) {
      patchRow(id, {
        validating: false,
        message: { kind: "error", text: err instanceof ApiError ? err.message : "Validate failed" },
      });
    }
  }

  async function onSync(id: string) {
    patchRow(id, { syncing: true, message: undefined });
    try {
      const res = await api.syncConnector(id);
      patchRow(id, {
        syncing: false,
        message: { kind: "info", text: `Sync queued — job ${res.job_id.slice(0, 8)} (see Jobs)` },
      });
    } catch (err) {
      patchRow(id, {
        syncing: false,
        message: { kind: "error", text: err instanceof ApiError ? err.message : "Sync failed" },
      });
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-100">Connectors</h1>
        <p className="mt-1 text-sm text-slate-500">
          Connect external sources (databases, APIs, S3). Validate the connection, then sync to
          pull, embed, and index records incrementally.
        </p>
      </div>

      <form onSubmit={onCreate} className="card space-y-4 p-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Name">
            <input
              className="input"
              placeholder="my-orders-db"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </Field>
          <Field label="Type">
            <select className="input" value={type} onChange={(e) => onTypeChange(e.target.value as ConnectorType)}>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Config (JSON)">
          <textarea
            className="input min-h-[180px] resize-y font-mono text-xs"
            value={configText}
            onChange={(e) => setConfigText(e.target.value)}
            spellCheck={false}
          />
        </Field>
        {formMsg && <Alert kind={formMsg.kind}>{formMsg.text}</Alert>}
        <button className="btn-primary" disabled={creating || !name.trim()}>
          {creating ? <Spinner /> : "Create connector"}
        </button>
      </form>

      {error && <Alert kind="error">{error}</Alert>}

      <div className="space-y-3">
        {loading && (
          <div className="card p-6 text-center text-slate-500">
            <Spinner /> Loading…
          </div>
        )}
        {!loading && connectors.length === 0 && (
          <div className="card p-6 text-center text-slate-500">
            No connectors yet — create one above.
          </div>
        )}
        {connectors.map((c) => {
          const st = rowState[c.id] ?? {};
          return (
            <div key={c.id} className="card p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-medium text-slate-100">{c.name}</div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                    <span className="rounded bg-white/5 px-1.5 py-0.5 text-brand-400">
                      {c.connector_type}
                    </span>
                    <span className="font-mono">{c.id.slice(0, 8)}</span>
                    {Object.keys(c.cursor ?? {}).length > 0 && <span>· synced</span>}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button className="btn-ghost" onClick={() => onValidate(c.id)} disabled={st.validating}>
                    {st.validating ? <Spinner /> : "Validate"}
                  </button>
                  <button className="btn-primary" onClick={() => onSync(c.id)} disabled={st.syncing}>
                    {st.syncing ? <Spinner /> : "Sync now"}
                  </button>
                </div>
              </div>
              {st.message && (
                <div className="mt-3">
                  <Alert kind={st.message.kind}>{st.message.text}</Alert>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
