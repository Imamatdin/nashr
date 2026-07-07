// Thin client for the privileged FastAPI tier (plan §4). Every mutation and
// door proof goes here; Supabase is only read directly (RLS + Realtime).

import { type AppSession, saveSession } from "./session";

interface MintedSessionWire {
  access_token: string;
  token_type: string;
  expires_at: string;
  user_id: string;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly reason: string,
  ) {
    super(`API ${status}: ${reason}`);
  }
}

function apiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) throw new Error("NEXT_PUBLIC_API_BASE_URL is not configured");
  return base.replace(/\/$/, "");
}

async function postJson<T>(path: string, body: unknown, token?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    // detail is not always a string (panel finding): FastAPI validation errors
    // carry an array, which would ride into React children and crash a render.
    const detail = await response
      .json()
      .then((data: { detail?: unknown }) =>
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail ?? "unknown").slice(0, 300),
      )
      .catch(() => "unknown");
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

function toSession(wire: MintedSessionWire): AppSession {
  return {
    accessToken: wire.access_token,
    expiresAt: wire.expires_at,
    userId: wire.user_id,
  };
}

export async function telegramLogin(initData: string): Promise<AppSession> {
  const wire = await postJson<MintedSessionWire>("/auth/telegram", { init_data: initData });
  const session = toSession(wire);
  saveSession(session);
  return session;
}

export async function emailExchange(supabaseAccessToken: string): Promise<AppSession> {
  const wire = await postJson<MintedSessionWire>("/auth/email/exchange", {
    supabase_access_token: supabaseAccessToken,
  });
  const session = toSession(wire);
  saveSession(session);
  return session;
}
