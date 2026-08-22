"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

/* ─────────────────────────────────────────────────────────
 * THINKING — expandable agent trace, four variants
 *
 *   Steps      step list with spinner → muted checks
 *   Reasoning  prose reasoning that expands, then settles
 *   Search     web-search trace: query + sources read
 *   Coding     tool trace: files read, edits, commands
 *
 * The trace runs once, settles, and remains expandable.
 * ───────────────────────────────────────────────────────── */

// Ported from beautifului.dev "thinking-state" (MIT). Kept: all four variant renderings, the
// shimmer-text header + chevron, the measured trace line (traceRef offsetHeight -> line height
// transition), the 1fr/0fr expand grammar, the per-row fade-up stagger, and the fire-once
// onSettled ref.
// Replaced: useSequence/STAGES and the VARIANTS fixture -> `working` / `visible` / `rows` props.

export type ThinkingVariant = "Steps" | "Reasoning" | "Search" | "Coding";

export interface ThinkingRow {
  primary: string;
  secondary?: string;
  mono?: boolean;
  add?: number;
  del?: number;
  href?: string;
}

export interface ThinkingStateProps {
  working: boolean;
  activeLabel: string;
  doneLabel: string;
  rows: ThinkingRow[];
  visible?: number;
  expanded?: boolean;
  onToggle?: (next: boolean) => void;
  variant?: ThinkingVariant;
  query?: string;
  selectedTool?: string | null;
  onSelectTool?: (tool: string | null) => void;
  moreCount?: number;
  onSettled?: () => void;
}

function Dot({ tone }: { tone: string }) {
  return (
    <span
      className={`flex size-3.5 shrink-0 items-center justify-center rounded-full text-on-accent ${tone}`}
    >
      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
        <circle cx="12" cy="12" r="9" />
        <path d="M3.5 12h17M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
      </svg>
    </span>
  );
}

const TONES = ["bg-accent", "bg-orange", "bg-green"];

export function ThinkingState({
  working,
  activeLabel,
  doneLabel,
  rows,
  visible,
  expanded,
  onToggle,
  variant = "Steps",
  query,
  selectedTool,
  onSelectTool,
  moreCount,
  onSettled,
}: ThinkingStateProps) {
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);
  const [internalTool, setInternalTool] = useState<string | null>(null);
  const autoExpanded = working;
  const isExpanded = expanded ?? manualExpanded ?? autoExpanded;
  const shown = visible ?? rows.length;
  const activeTool = selectedTool !== undefined ? selectedTool : internalTool;
  const traceRef = useRef<HTMLDivElement>(null);
  const [lineHeight, setLineHeight] = useState(0);
  useLayoutEffect(() => {
    if (traceRef.current) setLineHeight(traceRef.current.offsetHeight);
  }, [shown, isExpanded, variant, rows]);

  /* let embedders sequence content after the trace settles */
  const settledRef = useRef(false);
  useEffect(() => {
    if (working) {
      settledRef.current = false;
      return;
    }
    if (settledRef.current) return;
    settledRef.current = true;
    onSettled?.();
  }, [working, onSettled]);

  const toggle = () => {
    const next = !isExpanded;
    setManualExpanded(next);
    onToggle?.(next);
  };

  const pickTool = (tool: string | null) => {
    if (selectedTool === undefined) setInternalTool(tool);
    onSelectTool?.(tool);
  };

  return (
    <div
      className="flex w-full max-w-95 flex-col"
      style={{
        minHeight: working || isExpanded ? 176 : undefined,
        transition: "min-height 400ms cubic-bezier(0.23,1,0.32,1)",
      }}
    >
      {/* header — shared across variants */}
      <button
        type="button"
        aria-expanded={isExpanded}
        onClick={toggle}
        className="-mx-1.5 flex w-fit items-center gap-2 rounded-control px-1.5 py-1
          transition-colors duration-100 hover:bg-hover-2"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill={working ? "var(--ink-2)" : "var(--ink-3)"}>
          <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
        </svg>
        <span role="status" className="contents">
          {working ? (
            <span
              className="bg-clip-text text-[13px] font-medium whitespace-nowrap text-transparent"
              style={{
                backgroundImage:
                  "linear-gradient(90deg, var(--ink-3) 35%, var(--ink) 50%, var(--ink-3) 65%)",
                backgroundSize: "200% 100%",
                animation: "shimmer-text 1.4s linear infinite",
              }}
            >
              {activeLabel}
            </span>
          ) : (
            <span
              className="text-[13px] font-medium whitespace-nowrap text-ink-2"
              style={{ animation: "fade-in 350ms ease-out both" }}
            >
              {doneLabel}
            </span>
          )}
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--ink-3)"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="transition-transform duration-300"
          style={{ transform: isExpanded ? "rotate(180deg)" : "rotate(0)" }}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {/* expandable trace */}
      <div
        className="grid transition-[grid-template-rows,opacity] duration-400"
        style={{
          gridTemplateRows: isExpanded ? "1fr" : "0fr",
          opacity: isExpanded ? 1 : 0,
          transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
        }}
      >
        <div className="overflow-hidden">
          <div className="relative mt-1 ml-[5px] pl-4">
            <span
              aria-hidden
              className="absolute left-[3px] w-px bg-line"
              style={{
                top: -8,
                height: lineHeight ? lineHeight - 2 : 0,
                transition: "height 500ms cubic-bezier(0.23,1,0.32,1)",
              }}
            />
            <div ref={traceRef} className="flex flex-col gap-1 py-1">
              {query && (
                <div
                  className="flex h-6 items-center gap-2 px-1.5"
                  style={{
                    animation: isExpanded ? "fade-up 300ms cubic-bezier(0.23,1,0.32,1) both" : undefined,
                  }}
                >
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
                  <span className="text-[12.5px] text-ink-2">{query}</span>
                </div>
              )}
              {rows.slice(0, shown).map((row, i) => {
                const content = (
                  <>
                    {variant === "Search" && <Dot tone={TONES[i % 3]} />}
                    {variant === "Steps" &&
                      (i < shown - 1 || !working ? (
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="var(--ink-3)"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className="shrink-0"
                        >
                          <path d="M20 6L9 17l-5-5" />
                        </svg>
                      ) : (
                        <span
                          className="size-3 shrink-0 rounded-full border-[1.5px] border-line-strong border-t-ink-2"
                          style={{ animation: "spin 700ms linear infinite" }}
                        />
                      ))}
                    <span
                      className={`min-w-0 truncate text-[12.5px] ${variant === "Reasoning" ? "whitespace-normal leading-relaxed text-ink-2" : "font-medium text-ink"} ${variant === "Search" ? "animated-underline" : ""}`}
                    >
                      {row.primary}
                    </span>
                    {row.secondary && (
                      <span
                        className={`shrink-0 text-[11.5px] text-ink-3 ${row.mono ? "font-mono" : ""}`}
                      >
                        {row.secondary}
                      </span>
                    )}
                    {row.add !== undefined && (
                      <span className="shrink-0 font-mono text-[11px] tabular-nums">
                        <span className="text-green">+{row.add}</span>{" "}
                        <span className="text-red">−{row.del}</span>
                      </span>
                    )}
                  </>
                );
                const rowClass =
                  "flex min-h-7 w-full items-center gap-2 rounded-[6px] px-1.5 py-0.5 text-left";
                const animation = {
                  animation: `fade-up 320ms cubic-bezier(0.23,1,0.32,1) ${i * 120}ms both`,
                };

                if (variant === "Search") {
                  return (
                    <a
                      key={row.primary}
                      href={row.href}
                      target="_blank"
                      rel="noreferrer"
                      className={`${rowClass} transition-colors duration-150 hover:bg-hover`}
                      style={animation}
                    >
                      {content}
                    </a>
                  );
                }

                if (variant === "Coding") {
                  const selected = activeTool === row.primary;
                  return (
                    <button
                      key={row.primary}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => pickTool(selected ? null : row.primary)}
                      className={`${rowClass} transition-colors duration-150 ${selected ? "bg-inset" : "hover:bg-hover"}`}
                      style={animation}
                    >
                      {content}
                    </button>
                  );
                }

                return (
                  <div key={row.primary} className={rowClass} style={animation}>
                    {content}
                  </div>
                );
              })}
              {variant === "Search" && !working && moreCount ? (
                <span className="text-[12px] text-ink-3" style={{ animation: "fade-in 300ms ease-out both" }}>
                  +{moreCount} more
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ThinkingState;
