"use client";

// The authed shell: proves the whole identity chain end to end — app JWT →
// Supabase RLS read of the user's own projects. This page IS the P1 gate's
// positive half; the negative half (cannot read another user's rows) is the
// two-account test in the gate script. P3 adds creation (via the API, which
// holds the service role) and links into each project's workspace.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell, EmptyState, ErrorState, Skeleton, StatusBadge } from "@/components/ui";
import { createProject } from "@/lib/api";
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
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

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
      router.replace("/login");
      return;
    }
    setSession(active);
    refresh(active);
  }, [router, refresh]);

  async function onCreate() {
    if (!session || !title.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const project = await createProject(title.trim(), session.accessToken);
      router.push(`/projects/${project.id}`);
    } catch (createError) {
      setError(String(createError));
      setCreating(false);
    }
  }

  return (
    <AppShell authed>
      <h1>Loyihalarim</h1>

      <div className="card" style={{ marginBottom: "var(--sp-5)" }}>
        <div className="field-row">
          <input
            className="input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void onCreate();
            }}
            placeholder="Yangi loyiha nomi — masalan, «Yoritish davri»"
            maxLength={200}
          />
          <button
            className="btn btn-primary"
            onClick={() => void onCreate()}
            disabled={creating || !title.trim()}
          >
            {creating ? "Yaratilmoqda…" : "Loyiha yaratish"}
          </button>
        </div>
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
            hint="Yuqorida nom yozib birinchi loyihangizni yarating — keyin manba yuklab, taqdimot buyurtma qilasiz."
          />
        </div>
      )}

      {projects !== null && projects.length > 0 && (
        <div style={{ display: "grid", gap: "var(--sp-4)" }}>
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
                <div style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {project.title}
                </div>
                <div style={{ color: "var(--muted)", fontSize: "var(--text-sm)" }}>
                  {project.type === "presentation" ? "Taqdimot" : project.type}
                </div>
              </div>
              <StatusBadge status={project.status} />
            </Link>
          ))}
        </div>
      )}
    </AppShell>
  );
}
