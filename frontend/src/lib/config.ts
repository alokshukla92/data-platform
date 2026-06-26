// Resolves per-service base URLs from runtime config (window.__APP_CONFIG__),
// falling back to relative paths so that behind the k8s ingress the browser
// hits the same origin and the ingress routes /api/* to the right service.
const cfg = window.__APP_CONFIG__ ?? {};

export const API = {
  gateway: cfg.gatewayUrl ?? "",
  ingestion: cfg.ingestionUrl ?? "",
  retrieval: cfg.retrievalUrl ?? "",
};
