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
import { DataText, EmptyState, ErrorState, Skeleton, StatusBadge } from "@/components/ui";
import { type AppSession, loadSession } from "@/lib/session";
import { createRlsClient } from "@/lib/supabase";

interface ProjectRow {
  id: string;
  title: string;
  type: string;
  status: string;
  created_at: string | null;
}

const TYPE_LABEL: Record<string, string> = {
  presentation: "Taqdimot",
  article: "Maqola",
};

// dd.mm.yyyy — a filing date, not a "3 days ago" that ages behind the user's
// back. Tabular figures keep the column edge straight down the list.
function filedOn(value: string | null): string {
  if (!value) return "—";
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) return "—";
  const pad = (part: number) => part.toString().padStart(2, "0");
  return `${pad(when.getDate())}.${pad(when.getMonth() + 1)}.${when.getFullYear()}`;
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
      .select("id,title,type,status,created_at")
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
      <div className="page-bar">
        <div className="page-head">
          <p className="kicker">Ish stoli</p>
          <h1 className="page-title">Loyihalar</h1>
        </div>
        {/* One action per view: when the folio is empty the gilded moment moves
            into the empty state, so the two never appear together. */}
        {projects !== null && projects.length > 0 && (
          <Link href="/new" className="btn btn-gilded">
            Yangi loyiha
          </Link>
        )}
      </div>

      {error && (
        <ErrorState message={error} onRetry={session ? () => refresh(session) : undefined} />
      )}

      {projects === null && !error && (
        <div className="card">
          <Skeleton lines={4} />
        </div>
      )}

      {projects !== null && projects.length === 0 && !error && (
        <EmptyState
          title="Hozircha loyiha yo'q"
          hint="Birinchi loyihangizni boshlang — manba yuklaysiz, talablarni aytasiz, taqdimot yig'iladi."
        >
          <Link href="/new" className="btn btn-gilded">
            Birinchi loyiha
          </Link>
        </EmptyState>
      )}

      {projects !== null && projects.length > 0 && (
        <>
          <div className="folio-list">
            {projects.map((project) => (
              <Link key={project.id} href={`/projects/${project.id}`} className="folio-row">
                <span className="folio-row-main">
                  <span className="folio-row-title">{project.title}</span>
                  <span className="folio-row-meta">
                    {TYPE_LABEL[project.type] ?? project.type}
                    <span aria-hidden>·</span>
                    <DataText>{project.id.slice(0, 8)}</DataText>
                  </span>
                </span>
                <DataText className="folio-row-date">{filedOn(project.created_at)}</DataText>
                <StatusBadge status={project.status} />
                <span className="folio-row-arrow" aria-hidden />
              </Link>
            ))}
          </div>
          <p className="page-count">
            <DataText>{projects.length}</DataText> ta loyiha
          </p>
        </>
      )}
    </AppChrome>
  );
}
