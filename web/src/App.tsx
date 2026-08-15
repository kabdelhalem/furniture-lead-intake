import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import QueuePage from "./routes/QueuePage";
import LeadDetailPage from "./routes/LeadDetailPage";
import DashboardPage from "./routes/DashboardPage";
import ThresholdsPage from "./routes/ThresholdsPage";
import { REVIEWER } from "./lib/reviewer";

const NAV = [
  { to: "/queue", label: "Queue" },
  { to: "/dashboard", label: "Dashboard" },
  { to: "/thresholds", label: "Thresholds" },
];

function Masthead() {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-paper/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-5 py-3">
        <NavLink to="/queue" className="flex items-center gap-3">
          {/* A tiny caliper mark — the bench's stamp. */}
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-[7px] bg-brand text-panel">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M4 5v14M20 5v14M4 12h16" strokeLinecap="round" />
              <path d="M9 5v4M15 5v4" strokeLinecap="round" />
            </svg>
          </span>
          <span className="leading-tight">
            <span className="block font-semibold tracking-tight">Review Bench</span>
            <span className="eyebrow">Lead intake · per-field confidence</span>
          </span>
        </NavLink>

        <nav className="ml-4 flex items-center gap-1" aria-label="Primary">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-ink text-panel"
                    : "text-ink-soft hover:bg-panel-2 hover:text-ink"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2.5 text-right">
          <span className="hidden sm:block leading-tight">
            <span className="block text-sm font-medium">{REVIEWER.name}</span>
            <span className="eyebrow">{REVIEWER.role}</span>
          </span>
          <span
            aria-hidden
            className="grid h-9 w-9 place-items-center rounded-full border border-line-strong bg-panel font-mono text-xs font-bold text-brand-deep"
          >
            {REVIEWER.initials}
          </span>
        </div>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <div className="min-h-screen">
      <Masthead />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/queue" replace />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/leads/:id" element={<LeadDetailPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/thresholds" element={<ThresholdsPage />} />
          <Route path="*" element={<Navigate to="/queue" replace />} />
        </Routes>
      </main>
      <footer className="mx-auto max-w-6xl px-5 pb-10 pt-2">
        <p className="eyebrow">
          Reference implementation · offline replay from the recorded model cache
        </p>
      </footer>
    </div>
  );
}
