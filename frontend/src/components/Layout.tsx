import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../store/auth";

const navItems = [
  { to: "/search", label: "Search" },
  { to: "/upload", label: "Ingest" },
  { to: "/jobs", label: "Jobs" },
];

export default function Layout() {
  const { principal, logout } = useAuth();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-white/10 bg-ink-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-500/20 text-brand-400">
                <span className="text-lg">◆</span>
              </div>
              <span className="font-semibold tracking-tight text-slate-100">
                Data Intelligence
              </span>
            </div>
            <nav className="flex items-center gap-1">
              {navItems.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  className={({ isActive }) =>
                    `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                      isActive
                        ? "bg-white/10 text-white"
                        : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
                    }`
                  }
                >
                  {n.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm">
            {principal && (
              <span className="hidden text-slate-400 sm:inline">
                {principal.subject.slice(0, 8)}…{" "}
                <span className="rounded bg-white/5 px-1.5 py-0.5 text-xs text-brand-400">
                  {principal.role}
                </span>
              </span>
            )}
            <button className="btn-ghost" onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
