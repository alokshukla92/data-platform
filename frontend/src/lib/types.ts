export type Role = "admin" | "editor" | "viewer";

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface Principal {
  subject: string;
  tenant_id: string;
  role: Role;
  auth_method: string;
}

export type JobStatus =
  | "pending"
  | "processing"
  | "succeeded"
  | "failed"
  | "dead_lettered"
  | "retrying";

export interface Job {
  id: string;
  status: JobStatus;
  source_uri: string | null;
  attempts: number;
  max_attempts: number;
  error: string | null;
  job_metadata: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface UploadResponse {
  job_id: string;
  status: JobStatus;
  idempotency_key: string;
}

export type ConnectorType = "rest" | "csv" | "pdf" | "postgres" | "s3";

export interface Connector {
  id: string;
  name: string;
  connector_type: ConnectorType;
  is_active: boolean;
  cursor: Record<string, unknown>;
  created_at: string;
}

export interface ConnectorValidation {
  ok: boolean;
  detail: string | null;
}

export type SearchMode = "semantic" | "keyword" | "hybrid";

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface SearchResponse {
  query: string;
  mode: SearchMode;
  hits: SearchHit[];
}
