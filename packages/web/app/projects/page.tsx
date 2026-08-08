"use client";

// The authed shell: proves the whole identity chain end to end — app JWT →
// Supabase RLS read of the user's own projects. This page IS the P1 gate's
// positive half; the negative half (cannot read another user's rows) is the
// two-account test in the gate script. P3 adds creation (via the API, which
// holds the service role) and links into each project's workspace.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
    <main>
      <h1>Loyihalarim</h1>
      {error && <p style={{ color: "crimson" }}>Xato: {error}</p>}
      <p>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Yangi loyiha nomi"
          maxLength={200}
        />{" "}
        <button onClick={() => void onCreate()} disabled={creating || !title.trim()}>
          {creating ? "Yaratilmoqda…" : "Loyiha yaratish"}
        </button>
      </p>
      {projects === null && !error && <p>Yuklanmoqda…</p>}
      {projects !== null && projects.length === 0 && <p>Hozircha loyiha yo‘q.</p>}
      {projects !== null && projects.length > 0 && (
        <ul>
          {projects.map((project) => (
            <li key={project.id}>
              <Link href={`/projects/${project.id}`}>{project.title}</Link> — {project.type} (
              {project.status})
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
