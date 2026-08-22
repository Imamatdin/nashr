"use client";

import type { ReactNode } from "react";
import GlideMenu from "@/components/bui/glide-menu";

/* ─────────────────────────────────────────────────────────
 * SEARCH — command search with live filtering.
 * The field, clear action, and results are directly usable.
 * ───────────────────────────────────────────────────────── */

// Ported from beautifului.dev "search" (MIT). Kept: the input row with its hover tint and search
// glyph, the fade-in clear button, the empty state block, and the GlideMenu result rows with their
// fade-in and z-10 stacking above the gliding highlight.
// Replaced: the ITEMS fixture and internal query state -> controlled `query`/`onQueryChange` with a
// caller-filtered `results`; the empty-state copy -> `emptyTitle`/`emptyHint` props; the import path
// `@/components/primitives/GlideMenu` -> `@/components/bui/glide-menu`.

export interface SearchResult {
  key: string;
  label: string;
  meta?: string;
}

export interface SearchListProps {
  query: string;
  onQueryChange: (query: string) => void;
  placeholder: string;
  results: SearchResult[];
  renderRow?: (result: SearchResult) => ReactNode;
  onPick?: (result: SearchResult) => void;
  emptyTitle: string;
  emptyHint: string;
  autoFocus?: boolean;
}

export function SearchList({
  query,
  onQueryChange,
  placeholder,
  results,
  renderRow,
  onPick,
  emptyTitle,
  emptyHint,
  autoFocus,
}: SearchListProps) {
  const empty = results.length === 0;

  return (
    <div className="flex w-full max-w-72 flex-col items-stretch">
      <div className="w-full self-start overflow-hidden rounded-card bg-surface shadow-raised">
        {/* input row */}
        <div className="flex h-10 items-center gap-2 border-b border-line px-3 transition-colors duration-100 hover:bg-hover">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--ink-3)"
            strokeWidth="2"
            strokeLinecap="round"
            className="shrink-0"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="M21 21l-4.3-4.3" />
          </svg>
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={placeholder}
            aria-label={placeholder}
            autoFocus={autoFocus}
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3"
          />
          {query && (
            <button
              aria-label="Tozalash"
              type="button"
              onClick={() => onQueryChange("")}
              className="flex size-6 items-center justify-center rounded-full text-ink-3
                transition-colors duration-100 hover:bg-line/70 hover:text-ink"
              style={{ animation: "fade-in 150ms ease-out both" }}
            >
              <svg
                width="11"
                height="11"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
              >
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* results / empty state */}
        {empty ? (
          <div
            className="flex flex-col items-center justify-center gap-1 px-4 py-8"
            style={{ animation: "fade-in 250ms ease-out both" }}
          >
            <span className="mb-1.5 flex size-8 items-center justify-center rounded-control bg-inset text-ink-3 shadow-hairline">
              <svg
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              >
                <circle cx="11" cy="11" r="7" />
                <path d="M21 21l-4.3-4.3" />
              </svg>
            </span>
            <span className="text-[13px] font-medium text-ink">{emptyTitle}</span>
            <span className="text-[12px] text-ink-3">{emptyHint}</span>
          </div>
        ) : (
          <div className="p-1">
            <GlideMenu className="flex flex-col gap-px" highlightClassName="inset-x-0 rounded-[6px] bg-hover">
              {results.map((item) => (
                <button
                  key={item.key}
                  data-menu-row
                  type="button"
                  onClick={() => onPick?.(item)}
                  className="relative z-10 flex h-8 w-full items-center gap-2 rounded-[6px] px-2 text-left text-[13px] text-ink"
                  style={{ animation: "fade-in 200ms ease-out both" }}
                >
                  {renderRow ? (
                    renderRow(item)
                  ) : (
                    <>
                      <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      {item.meta && (
                        <span className="shrink-0 font-mono text-[11px] text-ink-3 tabular-nums">
                          {item.meta}
                        </span>
                      )}
                    </>
                  )}
                </button>
              ))}
            </GlideMenu>
          </div>
        )}
      </div>
    </div>
  );
}

export default SearchList;
