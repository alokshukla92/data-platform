import { useState } from "react";
import { ApiError } from "../lib/api";
import { useAuth } from "../store/auth";
import { Alert, Field, Spinner } from "../components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-brand-500/20 text-2xl text-brand-400">
            ◆
          </div>
          <h1 className="text-xl font-semibold text-slate-100">Data Intelligence Platform</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to ingest and search your data</p>
        </div>
        <form onSubmit={onSubmit} className="card space-y-4 p-6">
          {error && <Alert kind="error">{error}</Alert>}
          <Field label="Email">
            <input
              className="input"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </Field>
          <Field label="Password">
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          <button className="btn-primary w-full" disabled={busy}>
            {busy ? <Spinner /> : "Sign in"}
          </button>
        </form>
        <p className="mt-4 text-center text-xs text-slate-600">
          Bootstrap a tenant via <code className="text-slate-500">POST /api/v1/auth/bootstrap</code>
        </p>
      </div>
    </div>
  );
}
