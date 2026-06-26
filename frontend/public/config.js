// Default runtime config for `npm run dev` (points at the docker-compose backends).
// In a container this file is overwritten by docker-entrypoint.sh from env vars.
window.__APP_CONFIG__ = {
  gatewayUrl: "http://localhost:8000",
  ingestionUrl: "http://localhost:8001",
  retrievalUrl: "http://localhost:8002",
};
