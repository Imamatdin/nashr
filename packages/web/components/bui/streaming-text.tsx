"use client";

import { useEffect, useState } from "react";

/* ─────────────────────────────────────────────────────────
 * STREAMING TEXT
 * Words resolve out of blur, inline citations appear in
 * context, then actions and follow-up prompts become usable.
 * ───────────────────────────────────────────────────────── */

// Ported from beautifului.dev "streaming-text" (MIT). Kept: word tokenisation, the per-token
// stream-in blur reveal, the caret while streaming, the action row / sources disclosure with the
// 1fr/0fr grammar, and the follow-up rows with their fade-up stagger.
// Replaced: the TOKENS/FOLLOW_UPS/SOURCES fixtures -> `text` / `followUps` / `sources` props; the
// HOLD_MS restart loop -> no loop (streaming restarts only when `text` changes).
// Dropped: the mid-sentence SourceChip (bound to SOURCES[0], no marker exists in live prose) and
// the retry / thumbs-up / thumbs-down action buttons (demo affordances with no product action);
// Copy stays and writes the real text to the clipboard.

export interface StreamingSource {
  key: string;
  name: string;
  meta: string;
  href?: string;
}

export interface StreamingTextProps {
  text: string;
  active?: boolean;
  speed?: number;
  onDone?: () => void;
  sources?: StreamingSource[];
  followUps?: string[];
  onFollowUp?: (text: string) => void;
  fill?: boolean;
}

export function StreamingText({
  text,
  active = true,
  speed = 55,
  onDone,
  sources,
  followUps,
  onFollowUp,
  fill,
}: StreamingTextProps) {
  const tokens = text.split(" ").filter((word) => word.length > 0);
  const [count, setCount] = useState(active ? 0 : tokens.length);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const done = count >= tokens.length;

  useEffect(() => {
    setCount(active ? 0 : text.split(" ").filter((word) => word.length > 0).length);
  }, [text, active]);

  useEffect(() => {
    if (done) {
      onDone?.();
      return;
    }
    const t = setTimeout(() => setCount((c) => c + 1), speed);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count, done, speed]);

  return (
    <div className={fill ? "w-full" : "w-full max-w-95"}>
      <p className="text-[13px] leading-relaxed text-ink">
        {tokens.slice(0, count).map((token, i) => (
          <span
            key={i}
            className="inline [will-change:filter,opacity]"
            style={{ animation: "stream-in 420ms cubic-bezier(0.22,0.61,0.25,1) both" }}
          >
            {token}{" "}
          </span>
        ))}
        {!done && (
          <span
            className="ml-0.5 inline-block h-3 w-0.5 translate-y-0.5 rounded-full bg-ink"
            style={{ animation: "fade-in 150ms ease-out both" }}
          />
        )}
      </p>

      {/* action icons row */}
      {sources && sources.length > 0 && (
        <div
          className="mt-2 flex items-center gap-0.5 transition-opacity duration-400"
          style={{ opacity: done ? 1 : 0, pointerEvents: done ? "auto" : "none" }}
        >
          <button
            type="button"
            aria-label="Nusxa olish"
            onClick={() => {
              void navigator.clipboard?.writeText(text);
            }}
            className="flex size-6 items-center justify-center rounded-[6px] text-ink-3
              transition-colors duration-100 hover:bg-hover-2 hover:text-ink-2"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="9" y="9" width="12" height="12" rx="2.5" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
          </button>
          <button
            type="button"
            aria-expanded={sourcesOpen}
            onClick={() => setSourcesOpen((current) => !current)}
            className="ml-1.5 flex items-center gap-1.5 rounded-[6px] px-1 py-0.5 text-left transition-colors duration-150 hover:bg-hover"
          >
            <span className="flex -space-x-1">
              {sources.slice(0, 3).map((source) => (
                <span
                  key={source.key}
                  aria-hidden
                  className="flex size-3.5 items-center justify-center rounded-full bg-inset font-mono text-[7px] font-bold text-ink-2 shadow-[0_0_0_1.5px_var(--canvas)]"
                >
                  {source.name.slice(0, 1).toUpperCase()}
                </span>
              ))}
            </span>
            <span className="text-[12px] text-ink-2 tabular-nums">{sources.length} manba</span>
          </button>
        </div>
      )}

      {sources && sources.length > 0 && (
        <div
          className="grid transition-[grid-template-rows,opacity] duration-300"
          style={{
            gridTemplateRows: done && sourcesOpen ? "1fr" : "0fr",
            opacity: done && sourcesOpen ? 1 : 0,
            transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
          }}
        >
          <div className="overflow-hidden">
            <div className="mt-1.5 flex flex-col rounded-[10px] bg-inset p-1 shadow-hairline">
              {sources.map((source) => (
                <a
                  key={source.key}
                  href={source.href ?? "#"}
                  className="flex items-center gap-2 rounded-[6px] px-1.5 py-1 text-[12px] text-ink-2 transition-colors duration-150 hover:bg-hover hover:text-ink"
                >
                  <span
                    aria-hidden
                    className="flex size-4 items-center justify-center rounded-[4px] bg-surface font-mono text-[8px] font-bold text-ink-2 shadow-hairline"
                  >
                    {source.name.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="animated-underline min-w-0 truncate">{source.name}</span>
                  <span className="ml-auto shrink-0 font-mono text-[10.5px] text-ink-3">
                    {source.meta}
                  </span>
                </a>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* follow-ups */}
      {followUps && followUps.length > 0 && (
        <div
          className="mt-2.5 transition-opacity duration-400"
          style={{ opacity: done ? 1 : 0, pointerEvents: done ? "auto" : "none" }}
        >
          <p className="text-[12px] font-medium text-ink-2">Davomi</p>
          <div className="mt-0.5 flex flex-col">
            {followUps.map((item, i) => (
              <button
                key={item}
                type="button"
                onClick={() => onFollowUp?.(item)}
                className="-mx-1.5 flex items-center gap-2 rounded-[7px] border-b border-line
                  px-1.5 py-1.5 text-left text-[12.5px] text-ink transition-colors
                  duration-100 hover:bg-hover-2"
                style={
                  done
                    ? { animation: `fade-up 350ms cubic-bezier(0.23,1,0.32,1) ${i * 90}ms both` }
                    : { opacity: 0 }
                }
              >
                <svg
                  width="11"
                  height="11"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="var(--ink-3)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="shrink-0"
                >
                  <path d="M9 10l-5 5 5 5" />
                  <path d="M20 4v7a4 4 0 0 1-4 4H4" />
                </svg>
                {item}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default StreamingText;
