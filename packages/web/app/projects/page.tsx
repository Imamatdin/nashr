"use client";

// The authed shell: proves the whole identity chain end to end — app JWT →
// Supabase RLS read of the user's own projects. This page IS the P1 gate's
// positive half; the negative half (cannot read another user's rows) is the
// two-account test in the gate script.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { loadSession } from "@/lib/session";
import { createRlsClient } from "@/lib/supabase";

interface ProjectRow {
  id: string;
  title: string;
  type: string;
  status: string;
}

export default function ProjectsPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const session = loadSession();
    if (!session) {
      router.replace("/login");
      return;
    }
    const supabase = createRlsClient(session.accessToken);
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
  }, [router]);

  return (
    <main>
      <h1>Loyihalarim</h1>
      {error && <p style={{ color: "crimson" }}>Xato: {error}</p>}
      {projects === null && !error && <p>Yuklanmoqda…</p>}
      {projects !== null && projects.length === 0 && <p>Hozircha loyiha yo‘q.</p>}
      {projects !== null && projects.length > 0 && (
        <ul>
          {projects.map((project) => (
            <li key={project.id}>
              {project.title} — {project.type} ({project.status})
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
