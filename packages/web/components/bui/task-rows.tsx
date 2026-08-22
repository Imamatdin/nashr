"use client";

import { useState, type ReactNode } from "react";

/* ─────────────────────────────────────────────────────────
 * TASK ROWS
 *
 *     0ms   rows enter staggered (80ms apart)
 *   600ms   row 1 ring sweeps 0 → 66%
 *  1500ms   row 1 expands — detail steps drop down
 *  3900ms   row 1 collapses; row 2 flips to Failed + retry
 *  5300ms   row 2 resolves to Completed
 * The status run completes once; task details stay clickable.
 * ───────────────────────────────────────────────────────── */

// Ported from beautifului.dev "task-rows" (MIT). Kept: SpinnerRing dasharray, Badge pop-in,
// the Failed pill with its rotating retry glyph, manualOpen + 1fr/0fr expand grammar, the per-row
// fade-up stagger and per-detail stagger, the Capsules/List radius grammar.
// Replaced: useTick/TICKS and the fixture rows -> a `rows` prop driven by live job progress.

export type TaskRowStatus = "pending" | "running" | "completed" | "failed";

export interface TaskRowDetail {
  label: string;
  meta?: string;
}

export interface TaskRow {
  key: string;
  index: number;
  label: string;
  meta?: string;
  status: TaskRowStatus;
  details?: TaskRowDetail[];
}

export interface TaskRowsProps {
  rows: TaskRow[];
  variant?: "Capsules" | "List";
  autoOpenRunning?: boolean;
  onRetry?: (key: string) => void;
}

function SpinnerRing({ active, children }: { active?: boolean; children?: ReactNode }) {
  const size = 24,
    stroke = 2;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        className="absolute inset-0"
        style={active ? { animation: "spin 1.1s linear infinite" } : undefined}
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--line)"
          strokeWidth={stroke}
        />
        {active && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--ink-3)"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${c * 0.28} ${c * 0.72}`}
          />
        )}
      </svg>
      <span className="relative text-[10.5px] font-semibold tabular-nums text-ink">{children}</span>
    </span>
  );
}

function Badge({ tone, children }: { tone: "red" | "green"; children: ReactNode }) {
  return (
    <span
      className={`flex size-5.5 shrink-0 items-center justify-center rounded-full text-on-accent
        ${tone === "red" ? "bg-red" : "bg-green"}`}
      style={{ animation: "pop-in 300ms cubic-bezier(0.23,1,0.32,1) both" }}
    >
      {children}
    </span>
  );
}

const XIcon = (
  <svg
    width="12"
    height="12"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="3.5"
    strokeLinecap="round"
  >
    <path d="M18 6L6 18M6 6l12 12" />
  </svg>
);
const CheckIcon = (
  <svg
    width="13"
    height="13"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="3.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M20 6L9 17l-5-5" />
  </svg>
);
const RetryIcon = (
  <svg
    width="12"
    height="12"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="3"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
  </svg>
);

function badgeFor(row: TaskRow) {
  if (row.status === "completed") return <Badge tone="green">{CheckIcon}</Badge>;
  if (row.status === "failed") return <Badge tone="red">{XIcon}</Badge>;
  return <SpinnerRing active={row.status === "running"}>{row.index}</SpinnerRing>;
}

export function TaskRows({
  rows,
  variant = "Capsules",
  autoOpenRunning = true,
  onRetry,
}: TaskRowsProps) {
  const [manualOpen, setManualOpen] = useState<Record<string, boolean>>({});
  const list = variant === "List";

  return (
    <div
      className={`flex w-full max-w-110 flex-col ${
        list ? "gap-0 self-start overflow-hidden rounded-card bg-surface shadow-card" : "gap-2"
      }`}
    >
      {rows.map((row, i) => {
        const details = row.details ?? [];
        const open =
          manualOpen[row.key] ??
          (autoOpenRunning && row.status === "running" && details.length > 0);
        return (
          <div
            key={row.key}
            className={`self-stretch overflow-hidden transition-[border-radius,background-color] duration-300 hover:bg-inset ${
              list ? "border-b border-line last:border-0" : "bg-surface shadow-card"
            }`}
            style={{
              borderRadius: list ? 0 : open ? 14 : 22,
              animation: `fade-up 450ms cubic-bezier(0.23,1,0.32,1) ${i * 80}ms both`,
            }}
          >
            <button
              type="button"
              aria-expanded={open}
              disabled={details.length === 0}
              onClick={() => setManualOpen((current) => ({ ...current, [row.key]: !open }))}
              className="flex h-11 w-full items-center gap-2.5 px-2.5 text-left"
            >
              <span className="flex size-6 shrink-0 items-center justify-center">
                {badgeFor(row)}
              </span>
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">
                {row.label}
              </span>
              {row.meta && <span className="text-[12.5px] text-ink-2 tabular-nums">{row.meta}</span>}
              {row.status === "failed" ? (
                <span
                  className="inline-flex h-5.5 items-center gap-1.5 rounded-full bg-red-tint px-2 text-[11.5px] font-medium text-red"
                  style={{ animation: "fade-in 200ms ease-out both" }}
                >
                  Xatolik
                  <span
                    role="button"
                    tabIndex={0}
                    aria-label="Qayta urinish"
                    onClick={(event) => {
                      event.stopPropagation();
                      onRetry?.(row.key);
                    }}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.stopPropagation();
                      event.preventDefault();
                      onRetry?.(row.key);
                    }}
                    style={{ animation: "spin 1.2s linear infinite" }}
                    className="flex cursor-pointer"
                  >
                    {RetryIcon}
                  </span>
                </span>
              ) : row.status === "completed" ? (
                <span
                  className="inline-flex h-5.5 items-center gap-1.5 rounded-full bg-green-tint px-2 text-[11.5px] font-medium text-green"
                  style={{ animation: "fade-in 200ms ease-out both" }}
                >
                  Tayyor
                </span>
              ) : null}
              <span
                aria-hidden="true"
                className="-ml-2 flex size-7 shrink-0 items-center justify-center rounded-full text-ink-3"
              >
                {details.length > 0 && (
                  <svg
                    width="15"
                    height="15"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="transition-transform duration-300"
                    style={{ transform: open ? "rotate(180deg)" : "rotate(0)" }}
                  >
                    <path d="M6 9l6 6 6-6" />
                  </svg>
                )}
              </span>
            </button>

            {/* dropdown detail — same expandable grammar as Chain of Thought */}
            <div
              className="grid transition-[grid-template-rows,opacity] duration-300"
              style={{
                gridTemplateRows: open ? "1fr" : "0fr",
                opacity: open ? 1 : 0,
                transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
              }}
            >
              <div className="overflow-hidden">
                <div className="mb-2.5 grid grid-cols-[24px_1fr] gap-2.5 px-2.5">
                  <span aria-hidden className="mx-auto h-full w-px bg-line" />
                  <div className="flex flex-col gap-1.5">
                    {details.map((d, j) => (
                      <div
                        key={d.label}
                        className="flex items-center justify-between"
                        style={
                          open
                            ? {
                                animation: `fade-up 300ms cubic-bezier(0.23,1,0.32,1) ${120 + j * 100}ms both`,
                              }
                            : undefined
                        }
                      >
                        <span className="text-[12px] text-ink-2">{d.label}</span>
                        {d.meta && (
                          <span className="font-mono text-[11.5px] text-ink-3 tabular-nums">
                            {d.meta}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default TaskRows;
