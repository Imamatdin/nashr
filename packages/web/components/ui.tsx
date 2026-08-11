"use client";

// Shared presentational pieces of the P3.5 design system. Purely visual —
// no data fetching, no auth; pages own their state and pass it down.

import Link from "next/link";
import type { ReactNode } from "react";

export function AppShell({ children, authed }: { children: ReactNode; authed?: boolean }) {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="container topbar-inner">
          <Link href="/" className="wordmark">
            Nashr
          </Link>
          <nav className="nav-links">
            {authed ? (
              <Link href="/projects">Loyihalarim</Link>
            ) : (
              <Link href="/login" className="btn btn-primary">
                Kirish
              </Link>
            )}
          </nav>
        </div>
      </header>
      <main className="page">
        <div className="container">{children}</div>
      </main>
      <footer className="footer">
        <div className="container footer-inner">
          <span>© {new Date().getFullYear()} Nashr</span>
          <span>Manbaga asoslangan akademik nashrlar</span>
        </div>
      </footer>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  children,
}: {
  icon: string;
  title: string;
  hint: string;
  children?: ReactNode;
}) {
  return (
    <div className="state">
      <div className="state-icon" aria-hidden>
        {icon}
      </div>
      <h3>{title}</h3>
      <p>{hint}</p>
      {children}
    </div>
  );
}

export function ErrorState({
  title = "Nimadir xato ketdi",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state state-error">
      <div className="state-icon" aria-hidden>
        ⚠️
      </div>
      <h3>{title}</h3>
      <p>{message}</p>
      {onRetry && (
        <button className="btn btn-ghost" onClick={onRetry}>
          Qayta urinish
        </button>
      )}
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-busy="true" aria-label="Yuklanmoqda">
      {Array.from({ length: lines }, (_, index) => (
        <div
          key={index}
          className="skeleton"
          style={{ height: "1.1rem", marginBottom: "0.8rem", width: `${100 - index * 12}%` }}
        />
      ))}
    </div>
  );
}

export function Toast({ message, danger }: { message: string; danger?: boolean }) {
  return (
    <div className={danger ? "toast toast-danger" : "toast"} role="status">
      {message}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = {
    draft: "Qoralama",
    sourcing: "Manbalar",
    interview: "Suhbat",
    generating: "Yaratilmoqda",
    ready: "Tayyor",
    failed: "Xatolik",
    archived: "Arxiv",
    queued: "Navbatda",
    processing: "Jarayonda",
    completed: "Tayyor",
    cancelled: "Bekor qilingan",
  };
  const cls =
    status === "ready" || status === "completed"
      ? "badge badge-ok"
      : status === "failed" || status === "cancelled"
        ? "badge badge-danger"
        : status === "generating" || status === "processing" || status === "queued"
          ? "badge badge-busy"
          : "badge";
  return <span className={cls}>{label[status] ?? status}</span>;
}

// The worker's 7 pipeline steps (progress.step strings), humanized. Keys must
// match packages/bot/orchestrators/presentation_orchestrator.py verbatim.
export const STEP_LABELS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "Processing sources", label: "Manbalar o'qilmoqda" },
  { key: "Building evidence matrix", label: "Dalillar jamlanmoqda" },
  { key: "Applying preferences", label: "Talablar hisobga olinmoqda" },
  { key: "Choosing design direction", label: "Dizayn yo'nalishi tanlanmoqda" },
  { key: "Creating slide sequence", label: "Slaydlar ketma-ketligi tuzilmoqda" },
  { key: "Resolving images", label: "Vizuallar tayyorlanmoqda" },
  { key: "Rendering presentation", label: "Taqdimot yig'ilmoqda" },
];

export function GenerationSteps({ step, current }: { step?: string; current?: number }) {
  const activeIndex = STEP_LABELS.findIndex((s) => s.key === step);
  const done = activeIndex >= 0 ? activeIndex : Math.max(0, (current ?? 1) - 1);
  return (
    <ol className="steps">
      {STEP_LABELS.map((entry, index) => {
        const state = index < done ? "step-done" : index === done ? "step-current" : "";
        return (
          <li key={entry.key} className={`step ${state}`}>
            <span className="step-dot">{index < done ? "✓" : index + 1}</span>
            {entry.label}
          </li>
        );
      })}
    </ol>
  );
}

export function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}
