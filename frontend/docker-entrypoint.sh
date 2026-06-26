#!/bin/sh
set -e

# Generate runtime config from env vars so a single image works across environments.
# Empty values fall back to relative paths (used behind the k8s ingress).
cat > /usr/share/nginx/html/config.js <<EOF
window.__APP_CONFIG__ = {
  gatewayUrl: "${GATEWAY_URL:-}",
  ingestionUrl: "${INGESTION_URL:-}",
  retrievalUrl: "${RETRIEVAL_URL:-}",
};
EOF

exec nginx -g "daemon off;"
