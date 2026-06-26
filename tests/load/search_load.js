// k6 load test for the retrieval search endpoint.
// Usage: TOKEN=<jwt> k6 run tests/load/search_load.js
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const latency = new Trend("search_latency_ms", true);

export const options = {
  scenarios: {
    ramp: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: 20 }, // warm up
        { duration: "1m", target: 100 }, // sustained load
        { duration: "30s", target: 200 }, // spike
        { duration: "30s", target: 0 }, // ramp down
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"], // <1% errors
    http_req_duration: ["p(95)<500"], // p95 under 500ms
  },
};

const BASE = __ENV.RETRIEVAL_URL || "http://localhost:8002";
const TOKEN = __ENV.TOKEN || "";
const QUERIES = [
  "how does autoscaling work",
  "what is a circuit breaker",
  "explain gitops deployment",
  "vector search with pgvector",
];

export default function () {
  const q = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const res = http.post(
    `${BASE}/api/v1/search`,
    JSON.stringify({ query: q, mode: "hybrid", top_k: 5 }),
    { headers: { "Content-Type": "application/json", Authorization: `Bearer ${TOKEN}` } },
  );
  latency.add(res.timings.duration);
  check(res, { "status 200": (r) => r.status === 200 });
  sleep(Math.random());
}
