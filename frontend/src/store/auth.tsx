import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, getToken, setToken } from "../lib/api";
import type { Principal } from "../lib/types";

interface AuthState {
  principal: Principal | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Restore session on load if a token is present.
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setPrincipal)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      principal,
      loading,
      async login(email, password) {
        const tok = await api.login(email, password);
        setToken(tok.access_token);
        setPrincipal(await api.me());
      },
      logout() {
        setToken(null);
        setPrincipal(null);
      },
    }),
    [principal, loading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
