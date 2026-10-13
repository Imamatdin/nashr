"use client";

// Live job state for the workspace.
//
// Three audit gaps meet here:
//
//   G21 — Realtime was published for exactly this screen (migration 008 puts
//         generation_jobs and decks on supabase_realtime) and the web polled
//         every 3 s anyway, so step transitions landed up to 3 s late.
//   G6  — one failed poll ended the run. The `.catch` neither rescheduled nor
//         redirected, so a transient 500 or an expired token stopped the
//         watcher permanently while the job kept running server-side.
//   G7  — "Taqdimot tayyor. Fayllar tayyorlanmoqda." was permanent: the deck
//         was fetched once, the 404 was swallowed, and nothing ever asked again.
//
// So: Realtime is the fast path, polling is a fallback that BACKS OFF but never
// gives up, and a completed-but-deckless job keeps listening for the deck row.
//
// B1-FIX2 — a paid job is 'committed' while a separate render job publishes its
// files. The job view carries that render's status and progress, so this hook
// follows the parent to 'committed' and then the render: every change in the
// delivery fingerprint re-reads the exports (onDeckChanged). While anything is
// in flight it polls from 3 s backing off to 30 s, whether or not Realtime is
// connected and whether or not a deck exists yet.

import { useCallback, useEffect, useRef, useState } from "react";
import type { RealtimeChannel } from "@supabase/supabase-js";
import { ApiError, type JobView, getLatestJob } from "./api";
import { deliveryFingerprint, isInFlight, nextPollDelay, POLL_FIRST_MS } from "./delivery";
import type { AppSession } from "./session";
import { createRlsClient } from "./supabase";

/** Fast cadence right after something changed. */
const POLL_ACTIVE_MS = POLL_FIRST_MS;
/** Settled and Realtime connected: polling is only a safety net. */
const POLL_BACKGROUND_MS = 20_000;
/** Backoff ceiling for a poll that keeps failing or waiting. Never becomes "stop". */
const POLL_MAX_MS = 30_000;

export type JobLoadState = "loading" | "loaded" | "absent" | "error";

export interface LiveJob {
  job: JobView | null;
  state: JobLoadState;
  /** Last poll/subscribe failure, for an in-place banner (never a 4s toast). */
  error: unknown;
  /** True once the Realtime channel is actually subscribed. */
  live: boolean;
  /** Force an immediate re-read (used after enqueue and by a retry button). */
  refresh: () => void;
}

export interface LiveJobOptions {
  projectId: string;
  session: AppSession | null;
  withAuth: <T>(call: (token: string) => Promise<T>) => Promise<T | null>;
  /** Fired when the decks row changes — the workspace re-fetches signed URLs. */
  onDeckChanged: () => void;
  /**
   * False for a project that has no generation jobs (an article): nothing is
   * polled or subscribed, and the state is "absent" rather than a stream of 404s.
   */
  enabled?: boolean;
}

export function useLiveJob({
  projectId,
  session,
  withAuth,
  onDeckChanged,
  enabled = true,
}: LiveJobOptions): LiveJob {
  const [job, setJob] = useState<JobView | null>(null);
  const [state, setState] = useState<JobLoadState>("loading");
  const [error, setError] = useState<unknown>(null);
  const [live, setLive] = useState(false);

  const timer = useRef<number | null>(null);
  const backoff = useRef(POLL_ACTIVE_MS);
  const liveRef = useRef(false);
  const stopped = useRef(false);
  // Held in a ref so the poll loop can read the latest deck callback without
  // being torn down and rebuilt every time the parent re-renders.
  const deckCallback = useRef(onDeckChanged);
  deckCallback.current = onDeckChanged;
  // The last delivery fingerprint seen; a change re-reads the exports.
  const lastPrint = useRef<string | null>(null);

  const readJob = useCallback(async (): Promise<void> => {
    try {
      const view = await withAuth((token) => getLatestJob(projectId, token));
      if (stopped.current) return;
      if (view === null) return; // session gone; withAuth already redirected
      setJob(view);
      setState("loaded");
      setError(null);
      const print = deliveryFingerprint(view);
      const changed = print !== lastPrint.current;
      if (changed && lastPrint.current !== null) {
        // The render started, published, finished or failed: refresh downloads.
        deckCallback.current();
      }
      lastPrint.current = print;
      if (isInFlight(view)) {
        backoff.current = changed ? POLL_ACTIVE_MS : nextPollDelay(backoff.current);
      } else {
        backoff.current = liveRef.current ? POLL_BACKGROUND_MS : POLL_MAX_MS;
      }
    } catch (readError) {
      if (stopped.current) return;
      if (readError instanceof ApiError && readError.status === 404) {
        // "This project has never been generated" is a STATE, not a failure.
        setJob(null);
        setState("absent");
        setError(null);
        // Keep asking (3 s backing off to 30 s): a job may be enqueued elsewhere.
        backoff.current = nextPollDelay(backoff.current);
        return;
      }
      // Surface it, keep the last known job on screen, and keep watching. The
      // old code's `.catch` stopped here; a blip must not end the run.
      setError(readError);
      setState((current) => (current === "loading" ? "error" : current));
      backoff.current = Math.min(POLL_MAX_MS, Math.round(backoff.current * 1.8));
    }
  }, [projectId, withAuth]);

  const schedule = useCallback(
    (delay: number) => {
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        void readJob().then(() => {
          if (!stopped.current) schedule(backoff.current);
        });
      }, delay);
    },
    [readJob],
  );

  const refresh = useCallback(() => {
    backoff.current = POLL_ACTIVE_MS;
    void readJob().then(() => {
      if (!stopped.current) schedule(backoff.current);
    });
  }, [readJob, schedule]);

  useEffect(() => {
    stopped.current = false;
    if (!session) return;
    if (!enabled) {
      setJob(null);
      setState("absent");
      return;
    }

    void readJob().then(() => {
      if (!stopped.current) schedule(backoff.current);
    });

    let channel: RealtimeChannel | null = null;
    try {
      const supabase = createRlsClient(session.accessToken);
      channel = supabase
        .channel(`workspace:${projectId}`)
        .on(
          "postgres_changes",
          {
            event: "*",
            schema: "public",
            table: "generation_jobs",
            filter: `project_id=eq.${projectId}`,
          },
          () => {
            // The payload carries the row, but re-reading through the API keeps
            // ONE shape on screen (JobView, with the refund fact and the
            // payload-derived tier) instead of two that can disagree.
            void readJob();
          },
        )
        .on(
          "postgres_changes",
          // decks became a view of the document head (migration 016); a view
          // cannot be published, and a documents row changes exactly when the
          // head moves.
          { event: "*", schema: "public", table: "documents", filter: `project_id=eq.${projectId}` },
          () => deckCallback.current(),
        )
        .subscribe((status) => {
          const connected = status === "SUBSCRIBED";
          liveRef.current = connected;
          setLive(connected);
          // Dropped: return to the fast cadence rather than trusting a channel
          // that just failed. Connected: the next read picks the cadence, which
          // stays the in-flight backoff while a delivery is pending.
          if (!connected) backoff.current = POLL_ACTIVE_MS;
        });
    } catch {
      // Realtime is an optimisation. If the client cannot even be constructed
      // (missing env, blocked websocket), polling alone is still correct.
      liveRef.current = false;
      setLive(false);
    }

    return () => {
      stopped.current = true;
      if (timer.current !== null) window.clearTimeout(timer.current);
      if (channel) void channel.unsubscribe();
    };
  }, [projectId, session, enabled, readJob, schedule]);

  return { job, state, error, live, refresh };
}
