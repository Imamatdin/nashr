"use client";

// The authed shell: proves the whole identity chain end to end — app JWT →
// Supabase RLS read of the user's own projects. This page IS the P1 gate's
// positive half; the negative half (cannot read another user's rows) is the
// two-account test in the gate script. P3.6 moves it into the workspace chrome
// and hands creation over to /new.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppChrome } from "@/components/chrome";
import { EmptyState, ErrorState, Skeleton, StatusBadge } from "@/components/ui";
import { type AppSession, loadSession } from "@/lib/session";
import { createRlsClient } from "@/lib/supabase";

interface ProjectRow {
  id: string;
  title: string;
  type: string;
  status: string;
}

export default function ProjectsPage() {
  const router = useRouter();
  const [session, setSession] = useState<AppSession | null>(null);
  const [projects, setProjects] = useState<ProjectRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback((activeSession: AppSession) => {
    setError(null);
    const supabase = createRlsClient(activeSession.accessToken);
    supabase
      .from("projects")
      .select("id,title,type,status")
      .order("created_at", { ascending: false })
      .then(({ data, error: queryError }) => {
        if (queryError) {
          setError(queryError.message);
        } else {
          setProjects((data ?? []) as ProjectRow[]);
        }
      });
  }, []);

  useEffect(() => {
    const active = loadSession();
    if (!active) {
      router.replace("/login?returnTo=" + encodeURIComponent("/projects"));
      return;
    }
    setSession(active);
    refresh(active);
  }, [router, refresh]);

  return (
    <AppChrome active="projects">
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "var(--sp-4)",
          marginBottom: "var(--sp-5)",
        }}
      >
        <div className="page-head" style={{ marginBottom: 0 }}>
          <p className="kicker">Ish stoli</p>
          <h1 className="page-title">Loyihalar</h1>
        </div>
        <Link
          href="/new"
          className="btn btn-primary"
          style={{ background: "var(--gold)", color: "var(--siyoh)" }}
        >
          Yangi loyiha
        </Link>
      </div>

      {error && (
        <div className="card">
          <ErrorState message={error} onRetry={session ? () => refresh(session) : undefined} />
        </div>
      )}

      {projects === null && !error && (
        <div className="card">
          <Skeleton lines={4} />
        </div>
      )}

      {projects !== null && projects.length === 0 && !error && (
        <div className="card">
          <EmptyState
            icon="🗂️"
            title="Hozircha loyiha yo'q"
            hint="Birinchi loyihangizni boshlang — manba yuklaysiz, talablarni aytasiz, taqdimot yig'iladi."
          >
            <Link href="/new" className="btn btn-ghost">
              Yangi loyiha
            </Link>
          </EmptyState>
        </div>
      )}

      {projects !== null && projects.length > 0 && (
        <div style={{ display: "grid", gap: "var(--sp-3)" }}>
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/projects/${project.id}`}
              className="card card-hover"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "var(--sp-4)",
                color: "inherit",
                textDecoration: "none",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div
                  style={{
                    fontWeight: 600,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {project.title}
                </div>
                <div style={{ color: "var(--muted-ink)", fontSize: "var(--text-xs)" }}>
                  {project.type === "presentation" ? "Taqdimot" : project.type}
                </div>
              </div>
              <StatusBadge status={project.status} />
            </Link>
          ))}
        </div>
      )}
    </AppChrome>
  );
}
