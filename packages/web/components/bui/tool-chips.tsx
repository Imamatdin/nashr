"use client";

import { useState, type ReactNode, type SyntheticEvent } from "react";
import { createPortal } from "react-dom";

/* ─────────────────────────────────────────────────────────
 * TOOL CHIPS
 * An agent run as compact rows: tool calls with inline
 * chips, then file-diff chips summarizing the edits.
 * Hover a row to reveal its chevron; every row expands
 * to show what the tool actually did.
 * ───────────────────────────────────────────────────────── */

// Ported from beautifului.dev "tool-chips" (MIT). Kept: the collapsed run header, the per-row
// 1fr/0fr expand grammar, the icon→chevron hover swap, the chip/detail typography, the diff chips
// with their pop-in stagger, and the body-portal diff preview with its above/below flip.
// Replaced: the STEP_MS fake timer -> a `revealed` prop (rows appear as the caller adds them, each
// still entering with the fade-up); the ROWS/DIFFS/DIFF_LINES fixtures -> props.
// Added: a per-row status glyph (pending dot / done check / failed cross) in the Badge pop-in style.

export type ToolIcon = "think" | "write" | "run" | "read" | "file";
export type ToolRowState = "pending" | "done" | "failed";

export interface ToolDetailLine {
  text: string;
  tone?: "add" | "del" | "error";
}

export interface ToolRow {
  key: string;
  icon: ToolIcon;
  label: string;
  chip: string;
  mono?: boolean;
  detailMono?: boolean;
  state?: ToolRowState;
  detail: ToolDetailLine[];
}

export interface ToolDiff {
  file: string;
  add: number;
  del: number;
  lines?: Array<{ text: string; tone: "add" | "del" | "ctx" }>;
}

export interface ToolChipsProps {
  header: string;
  rows: ToolRow[];
  diffs?: ToolDiff[];
  open?: boolean;
  revealed?: number;
  onRowToggle?: (key: string, next: boolean) => void;
}

const Icons: Record<ToolIcon, ReactNode> = {
  think: <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />,
  write: (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z" />
    </g>
  ),
  run: (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 17l6-5-6-5M12 19h8" />
    </g>
  ),
  read: (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </g>
  ),
  file: (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4h6l2 3h8v13H4z" />
    </g>
  ),
};

function StatusGlyph({ state }: { state: ToolRowState }) {
  if (state === "pending") {
    return (
      <span
        aria-hidden
        className="size-2 shrink-0 rounded-full bg-ink-3"
        style={{ animation: "pixel-on 900ms ease-in-out infinite" }}
      />
    );
  }
  return (
    <span
      aria-hidden
      className={`flex size-3.5 shrink-0 items-center justify-center rounded-full text-on-accent ${
        state === "done" ? "bg-green" : "bg-red"
      }`}
      style={{ animation: "pop-in 300ms cubic-bezier(0.23,1,0.32,1) both" }}
    >
      <svg
        width="9"
        height="9"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {state === "done" ? <path d="M20 6L9 17l-5-5" /> : <path d="M18 6L6 18M6 6l12 12" />}
      </svg>
    </span>
  );
}

export function ToolChips({ header, rows, diffs, open, revealed, onRowToggle }: ToolChipsProps) {
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const [openRows, setOpenRows] = useState<Set<string>>(new Set());
  const isOpen = open ?? manualOpen ?? true;
  const shown = revealed ?? rows.length;
  /* Rendered in a body portal so animated/translated reply wrappers cannot
   * redefine the fixed-position coordinate system. */
  const [preview, setPreview] = useState<{
    file: string;
    x: number;
    top?: number;
    bottom?: number;
  } | null>(null);

  const linesFor = (file: string) => diffs?.find((diff) => diff.file === file)?.lines ?? [];

  const openPreview = (file: string) => (event: SyntheticEvent) => {
    const rect = (event.currentTarget as Element).closest("[data-diffchip]")!.getBoundingClientRect();
    const previewHeight = 38 + linesFor(file).length * 19;
    const fitsBelow = rect.bottom + 6 + previewHeight <= window.innerHeight - 12;
    setPreview({
      file,
      x: Math.max(12, Math.min(rect.left, window.innerWidth - 300)),
      ...(fitsBelow ? { top: rect.bottom + 6 } : { bottom: window.innerHeight - rect.top + 6 }),
    });
  };
  const closePreview = (file: string) => () =>
    setPreview((current) => (current?.file === file ? null : current));

  const toggleRow = (key: string) => {
    const next = !openRows.has(key);
    setOpenRows((current) => {
      const set = new Set(current);
      if (next) set.add(key);
      else set.delete(key);
      return set;
    });
    onRowToggle?.(key, next);
  };

  return (
    <div className="w-full max-w-80 pb-1">
      {/* collapsed run header */}
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setManualOpen(!isOpen)}
        className="-mx-1.5 flex w-fit items-center gap-1.5 rounded-control px-1.5 py-1 text-[12.5px] text-ink-2 transition-colors duration-100 hover:bg-hover-2"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="transition-transform duration-200"
          style={{ transform: isOpen ? "rotate(0deg)" : "rotate(-90deg)" }}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
        <span className="tabular-nums">{header}</span>
      </button>

      {/* tool call rows */}
      <div
        className="grid transition-[grid-template-rows,opacity] duration-300"
        style={{ gridTemplateRows: isOpen ? "1fr" : "0fr", opacity: isOpen ? 1 : 0 }}
      >
        {/* -mx-1 + px-1.5 keeps content at the same x while giving the
            row hover pills room inside this overflow-hidden clip box */}
        <div className="-mx-1 overflow-hidden px-1.5 pb-1">
          <div className="mt-1.5 flex flex-col gap-1">
            {rows.slice(0, shown).map((row) => {
              const rowOpen = openRows.has(row.key);
              return (
                <div
                  key={row.key}
                  style={{ animation: "fade-up 300ms cubic-bezier(0.23,1,0.32,1) both" }}
                >
                  <button
                    type="button"
                    aria-expanded={rowOpen}
                    onClick={() => toggleRow(row.key)}
                    className="group/row -mx-[3px] flex h-7 w-[calc(100%+6px)] min-w-0 items-center gap-2 rounded-control px-[3px] text-left transition-colors duration-100 hover:bg-hover-2"
                  >
                    <span className="relative flex size-4 shrink-0 items-center justify-center text-ink-3">
                      <svg
                        width="13"
                        height="13"
                        viewBox="0 0 24 24"
                        fill={row.icon === "think" ? "currentColor" : "none"}
                        stroke="currentColor"
                        className={`transition-opacity duration-100 group-hover/row:opacity-0 ${rowOpen ? "opacity-0" : ""}`}
                      >
                        {Icons[row.icon]}
                      </svg>
                      <svg
                        width="12"
                        height="12"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className={`absolute transition-[opacity,transform] duration-150 group-hover/row:opacity-100 ${rowOpen ? "opacity-100" : "opacity-0"}`}
                        style={{ transform: rowOpen ? "rotate(0deg)" : "rotate(-90deg)" }}
                      >
                        <path d="M6 9l6 6 6-6" />
                      </svg>
                    </span>
                    <span className="shrink-0 text-[12.5px] font-medium text-ink">{row.label}</span>
                    <span
                      className={`inline-flex h-5.5 min-w-0 flex-1 cursor-pointer items-center truncate rounded-chip bg-field px-1.5
                    text-[11.5px] text-ink-2 shadow-hairline transition-colors duration-100 hover:bg-hover-2
                    ${row.mono ? "font-mono" : ""}`}
                    >
                      {row.chip}
                    </span>
                    {row.state && <StatusGlyph state={row.state} />}
                  </button>

                  {/* expanded detail */}
                  <div
                    className="grid transition-[grid-template-rows,opacity] duration-300"
                    style={{
                      gridTemplateRows: rowOpen ? "1fr" : "0fr",
                      opacity: rowOpen ? 1 : 0,
                      transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
                    }}
                  >
                    <div className="min-h-0 overflow-hidden">
                      <div className="mt-0.5 mb-1 ml-2 flex flex-col gap-0.5 border-l border-line py-0.5 pl-3.5">
                        {row.detail.map((line) => (
                          <span
                            key={line.text}
                            className={`truncate text-[11.5px] leading-[1.6] ${row.detailMono ? "font-mono" : ""} ${
                              line.tone === "add"
                                ? "text-green"
                                : line.tone === "del"
                                  ? "text-orange"
                                  : line.tone === "error"
                                    ? "text-red"
                                    : "text-ink-2"
                            }`}
                          >
                            {line.text}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* file-diff chips */}
          {diffs && diffs.length > 0 && (
            <div className="mt-2.5 flex max-w-full flex-wrap gap-1.5 border-t border-line pt-2.5">
              {diffs.map((d, i) => (
                <span
                  key={d.file}
                  data-diffchip
                  className="relative"
                  onMouseEnter={openPreview(d.file)}
                  onMouseLeave={closePreview(d.file)}
                >
                  <button
                    type="button"
                    aria-expanded={preview?.file === d.file}
                    aria-label={`${d.file} farqini ko‘rsatish`}
                    onFocus={openPreview(d.file)}
                    onBlur={closePreview(d.file)}
                    className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-chip
                  bg-surface px-2 font-mono text-[11.5px] text-ink shadow-btn
                  transition-colors duration-100 hover:bg-hover"
                    style={{ animation: `pop-in 250ms cubic-bezier(0.23,1,0.32,1) ${i * 80}ms both` }}
                  >
                    <span className="min-w-0 truncate">{d.file}</span>
                    <span className="shrink-0 text-green tabular-nums">+{d.add}</span>
                    {d.del > 0 && <span className="shrink-0 text-red tabular-nums">−{d.del}</span>}
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      {preview &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="fixed z-50 w-72 overflow-hidden rounded-[10px] bg-surface shadow-overlay"
            style={{
              left: preview.x,
              top: preview.top,
              bottom: preview.bottom,
              animation: "pop-in 160ms cubic-bezier(0.23,1,0.32,1) both",
              transformOrigin: preview.top === undefined ? "bottom left" : "top left",
            }}
          >
            <div className="flex items-center justify-between border-b border-line px-2.5 py-1.5 font-mono text-[11px]">
              <span className="min-w-0 truncate text-ink-2">{preview.file}</span>
              <span className="shrink-0 tabular-nums">
                <span className="text-green">
                  +{diffs?.find((diff) => diff.file === preview.file)?.add}
                </span>
                {(diffs?.find((diff) => diff.file === preview.file)?.del ?? 0) > 0 && (
                  <span className="text-red">
                    {" "}
                    −{diffs?.find((diff) => diff.file === preview.file)?.del}
                  </span>
                )}
              </span>
            </div>
            <div className="py-1 font-mono text-[11px] leading-[1.8]">
              {linesFor(preview.file).map((line, index) => (
                <div
                  key={index}
                  className={`flex gap-2 px-2.5 whitespace-pre ${
                    line.tone === "add"
                      ? "bg-green-tint text-green"
                      : line.tone === "del"
                        ? "bg-red-tint text-red"
                        : "text-ink-2"
                  }`}
                >
                  <span className="w-3 shrink-0 select-none">
                    {line.tone === "add" ? "+" : line.tone === "del" ? "−" : " "}
                  </span>
                  <span className="min-w-0 truncate">{line.text}</span>
                </div>
              ))}
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

export default ToolChips;
