import { API } from "./config";
import type {
  Connector,
  ConnectorType,
  ConnectorValidation,
  Job,
  JobEvent,
  Page,
  Principal,
  SearchMode,
  SearchResponse,
  TokenResponse,
  UploadResponse,
} from "./types";

const TOKEN_KEY = "dp_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  base: string,
  path: string,
  opts: { method?: string; body?: unknown; auth?: boolean; form?: FormData } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  const init: RequestInit = { method: opts.method ?? "GET", headers };

  if (opts.auth !== false) {
    const t = getToken();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  }
  if (opts.form) {
    init.body = opts.form; // browser sets multipart boundary
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }

  const res = await fetch(`${base}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = (data?.detail as string) ?? detail;
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 429) detail = "Rate limit exceeded — slow down and retry.";
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // ---- auth (gateway) ----
  login(email: string, password: string) {
    return request<TokenResponse>(API.gateway, "/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
      auth: false,
    });
  },
  me() {
    return request<Principal>(API.gateway, "/api/v1/auth/me");
  },
  bootstrap(payload: {
    tenant_name: string;
    tenant_slug: string;
    admin_email: string;
    admin_password: string;
  }) {
    return request<{ tenant_id: string; admin_id: string }>(
      API.gateway,
      "/api/v1/auth/bootstrap",
      { method: "POST", body: payload, auth: false },
    );
  },

  // ---- ingestion ----
  uploadText(content: string, title?: string) {
    return request<UploadResponse>(API.ingestion, "/api/v1/ingest/text", {
      method: "POST",
      body: { content, title: title || null },
    });
  },
  uploadFile(file: File, title?: string) {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    return request<UploadResponse>(API.ingestion, "/api/v1/ingest/file", {
      method: "POST",
      form,
    });
  },
  listJobs(params: { status?: string; limit?: number; offset?: number } = {}) {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    q.set("limit", String(params.limit ?? 50));
    q.set("offset", String(params.offset ?? 0));
    return request<Page<Job>>(API.ingestion, `/api/v1/jobs?${q.toString()}`);
  },
  getJob(id: string) {
    return request<Job>(API.ingestion, `/api/v1/jobs/${id}`);
  },
  getJobHistory(id: string) {
    return request<JobEvent[]>(API.ingestion, `/api/v1/jobs/${id}/history`);
  },

  // ---- connectors (gateway) ----
  listConnectors() {
    return request<Page<Connector>>(API.gateway, "/api/v1/connectors?limit=100");
  },
  createConnector(name: string, connectorType: ConnectorType, config: Record<string, unknown>) {
    return request<Connector>(API.gateway, "/api/v1/connectors", {
      method: "POST",
      body: { name, connector_type: connectorType, config },
    });
  },
  validateConnector(id: string) {
    return request<ConnectorValidation>(API.gateway, `/api/v1/connectors/${id}/validate`, {
      method: "POST",
    });
  },
  syncConnector(id: string) {
    return request<UploadResponse>(API.gateway, `/api/v1/connectors/${id}/sync`, {
      method: "POST",
    });
  },

  // ---- retrieval ----
  search(query: string, mode: SearchMode, topK: number, alpha: number) {
    return request<SearchResponse>(API.retrieval, "/api/v1/search", {
      method: "POST",
      body: { query, mode, top_k: topK, alpha },
    });
  },
};
