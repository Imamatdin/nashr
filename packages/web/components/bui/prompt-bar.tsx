"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/* ─────────────────────────────────────────────────────────
 * PROMPT BAR
 * A composer with real controls: attach, @ data sources,
 * / commands, a model picker, dictation, and send.
 * Type @ or / to open the menus; ↑↓ + Enter to pick.
 * Variants: Rounded (card radius) · Pill (full radius).
 * ───────────────────────────────────────────────────────── */

// Ported from beautifului.dev "prompt-bar" (MIT). Kept: parseToken, the @ / slash menus with the
// single gliding highlight measured off rowRefs (offsetTop/offsetHeight), ArrowUp/ArrowDown/Enter/
// Tab/Escape navigation, the outside-click pointerdown close, the `expanded` width measurement plus
// textarea auto-height, the attachment chips with pop-in + remove, the plus button, the picker
// trigger with its measured menu (left/bottom off the composer anchor) and its own gliding
// highlight, and the send button's ink/line-strong state swap.
// Replaced: AUTO_STEPS/`demo` self-running loop -> fully controlled `value`/`onChange`/`onSend`;
// the SOURCES/COMMANDS/MODELS/FILES/BRANDS fixtures -> props; the single model picker -> N pickers
// sharing one measurement path; the fake attach rotation -> a hidden <input type=file multiple> that
// calls onAttach.
// Dropped: the glimm rainbow canvas sweep (WebGL dependency, decorative) and the dictation control
// with its eq-bounce meter (no speech backend); the source "Connect" affordance (no OAuth surface).

export type PromptGlyph = "clip" | "chart" | "layers" | "globe" | "file";

export interface PromptSource {
  key: string;
  name: string;
  desc: string;
  icon?: PromptGlyph;
  attach?: boolean;
}

export interface PromptCommand {
  key: string;
  name: string;
  desc: string;
}

export interface PromptPickerOption {
  key: string;
  name: string;
  tag?: string;
}

export interface PromptPicker {
  key: string;
  label: string;
  value: string;
  options: PromptPickerOption[];
  onChange: (key: string) => void;
}

export interface PromptBarProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  placeholder?: string;
  tall?: boolean;
  variant?: "Rounded" | "Pill";
  attachments?: string[];
  onAttach?: (files: File[]) => void;
  onRemoveAttachment?: (index: number) => void;
  sources?: PromptSource[];
  commands?: PromptCommand[];
  onCommand?: (cmd: string, arg: string) => void;
  pickers?: PromptPicker[];
  accept?: string;
  maxAttachments?: number;
  maxLength?: number;
  disabled?: boolean;
  busy?: boolean;
}

function Icon({
  children,
  size = 15,
  strokeWidth = 1.8,
}: {
  children: ReactNode;
  size?: number;
  strokeWidth?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const GLYPHS: Record<PromptGlyph, ReactNode> = {
  clip: (
    <path d="m21.4 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  ),
  chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  layers: (
    <g>
      <path d="M12 2 2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5M2 12l10 5 10-5" />
    </g>
  ),
  globe: (
    <g>
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </g>
  ),
  file: (
    <g>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </g>
  ),
};

/* the last @word or /word being typed, if any */
function parseToken(draft: string): { kind: "at" | "slash"; query: string; start: number } | null {
  const match = /(^|\s)([@/])([\w-]*)$/.exec(draft);
  if (!match) return null;
  return {
    kind: match[2] === "@" ? "at" : "slash",
    query: match[3].toLowerCase(),
    start: match.index + match[1].length,
  };
}

export function PromptBar({
  value,
  onChange,
  onSend,
  placeholder,
  tall = true,
  variant = "Rounded",
  attachments = [],
  onAttach,
  onRemoveAttachment,
  sources = [],
  commands = [],
  onCommand,
  pickers = [],
  accept,
  maxAttachments = 10,
  maxLength,
  disabled = false,
  busy = false,
}: PromptBarProps) {
  const pill = variant === "Pill";
  const [dismissed, setDismissed] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [openPicker, setOpenPicker] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const wide = expanded || tall;
  const [rowBox, setRowBox] = useState<{ top: number; height: number } | null>(null);
  const [engaged, setEngaged] = useState(false);
  const [pickerBox, setPickerBox] = useState<{ top: number; height: number } | null>(null);
  const [pickerHovered, setPickerHovered] = useState<number | null>(null);
  const [pickerMenuLeft, setPickerMenuLeft] = useState(0);
  const [pickerMenuBottom, setPickerMenuBottom] = useState(0);
  const composerAnchorRef = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const pickersRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pickerBtnRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const pickerRowRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const token = dismissed ? null : parseToken(value);
  const menu: "at" | "slash" | null = plusOpen ? "at" : (token?.kind ?? null);
  const query = plusOpen ? "" : (token?.query ?? "");

  const rows: { key: string; name: string; desc: string }[] =
    menu === "at"
      ? sources.filter((s) => s.name.toLowerCase().includes(query))
      : menu === "slash"
        ? commands.filter((c) => c.name.slice(1).startsWith(query))
        : [];

  const picker = pickers.find((p) => p.key === openPicker) ?? null;
  const pickerIndex = picker ? picker.options.findIndex((o) => o.key === picker.value) : 0;

  useEffect(() => {
    setActive(0);
    setEngaged(false);
  }, [menu, query]);

  /* a single highlight glides to the active row instead of each row
   * toggling its own background — matches the gliding pill in the nav */
  useLayoutEffect(() => {
    const target = rowRefs.current[active];
    if (target) setRowBox({ top: target.offsetTop, height: target.offsetHeight });
  }, [menu, query, active, rows.length]);

  /* same gliding highlight in the picker menu — floats to the hovered
   * row, falling back to the currently-selected option */
  useLayoutEffect(() => {
    if (!picker) return;
    const target = pickerRowRefs.current[pickerHovered ?? Math.max(0, pickerIndex)];
    if (target) setPickerBox({ top: target.offsetTop, height: target.offsetHeight });
  }, [picker, pickerHovered, pickerIndex]);

  /* The menu is outside the clipped composer, so align it to the picker
   * trigger by measurement instead of pinning it to the far-right edge. */
  useLayoutEffect(() => {
    const trigger = openPicker ? pickerBtnRefs.current[openPicker] : null;
    if (!openPicker || !composerAnchorRef.current || !trigger) return;
    const anchorRect = composerAnchorRef.current.getBoundingClientRect();
    const triggerRect = trigger.getBoundingClientRect();
    setPickerMenuLeft(
      Math.max(0, Math.min(triggerRect.left - anchorRect.left, anchorRect.width - 176)),
    );
    // their formula anchors the menu 8px above the trigger; in the tall composer the trigger sits
    // low inside the card, so clamp it to clear the whole composer instead of covering the prompt
    setPickerMenuBottom(
      Math.max(anchorRect.bottom - triggerRect.top + 8, anchorRect.height + 8),
    );
  }, [openPicker, wide, attachments.length]);

  useEffect(() => {
    if (!openPicker) setPickerHovered(null);
  }, [openPicker]);

  /* Move wrapped text above the controls, then grow to a compact maximum. */
  useLayoutEffect(() => {
    const input = inputRef.current;
    const controls = controlsRef.current;
    const measure = measureRef.current;
    const pickerGroup = pickersRef.current;
    if (!input || !controls || !measure) return;

    const fixedControlsWidth = 28 * 2 + (pickerGroup?.offsetWidth ?? 0);
    const inlineGaps = 4 * 3;
    const inlineInputWidth = controls.clientWidth - fixedControlsWidth - inlineGaps;
    const needsFullWidth = value.includes("\n") || measure.offsetWidth + 8 > inlineInputWidth;
    if (needsFullWidth !== expanded) {
      setExpanded(needsFullWidth);
    }

    const minHeight = 28;
    const maxHeight = 100;
    input.style.height = "0px";
    const contentHeight = input.scrollHeight;
    input.style.height = `${Math.min(Math.max(contentHeight, minHeight), maxHeight)}px`;
    input.style.overflowY = contentHeight > maxHeight ? "auto" : "hidden";
  }, [value, expanded, tall]);

  /* clicking anywhere outside the composer closes the open menus */
  useEffect(() => {
    if (!openPicker && !plusOpen) return;
    const close = (event: PointerEvent) => {
      if (!(event.target as Element).closest("[data-promptbar]")) {
        setOpenPicker(null);
        setPlusOpen(false);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [openPicker, plusOpen]);

  const closeMenus = () => {
    setPlusOpen(false);
    setOpenPicker(null);
  };

  const atCapacity = attachments.length >= maxAttachments;

  const pick = (row: { key: string; name: string }) => {
    const source = menu === "at" ? sources.find((s) => s.key === row.key) : undefined;
    if (source?.attach) {
      if (token) onChange(value.slice(0, token.start));
      if (!atCapacity) fileInputRef.current?.click();
    } else if (menu === "at") {
      onChange(`${token ? value.slice(0, token.start) : value}@${row.name} `);
    } else {
      onChange(`${token ? value.slice(0, token.start) : value}${row.name} `);
      onCommand?.(row.key, "");
    }
    setPlusOpen(false);
    setDismissed(false);
    inputRef.current?.focus();
  };

  const canSend = !disabled && !busy && (value.trim().length > 0 || attachments.length > 0);
  const send = () => {
    if (!canSend) return;
    onSend();
    closeMenus();
  };

  return (
    <div data-promptbar className="w-full">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={accept}
        className="hidden"
        onChange={(event) => {
          const picked = Array.from(event.target.files ?? []);
          const room = Math.max(0, maxAttachments - attachments.length);
          if (picked.length > 0 && room > 0) onAttach?.(picked.slice(0, room));
          event.target.value = "";
        }}
      />
      {/* composer is the anchor — menus grow up from its top edge */}
      <div ref={composerAnchorRef} className="relative">
        {/* ── @ / slash menu ─────────────────────────────── */}
        {menu && (
          <div
            onMouseLeave={() => setEngaged(false)}
            className="absolute inset-x-0 bottom-full z-10 mb-2 rounded-[10px] bg-surface p-1 shadow-raised"
            style={{
              animation: "pop-in 180ms cubic-bezier(0.23,1,0.32,1) both",
              transformOrigin: "bottom center",
            }}
          >
            {/* single gliding highlight — appears once a row is hovered */}
            <span
              aria-hidden
              className="pointer-events-none absolute inset-x-1 rounded-[6px] bg-hover"
              style={{
                top: rowBox?.top ?? 0,
                height: rowBox?.height ?? 0,
                opacity: rowBox && engaged && rows.length > 0 ? 1 : 0,
                transition:
                  "top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease",
              }}
            />
            {rows.map((row, i) => {
              const source = menu === "at" ? sources.find((s) => s.key === row.key) : undefined;
              return (
                <button
                  key={row.key}
                  type="button"
                  ref={(el) => {
                    rowRefs.current[i] = el;
                  }}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => {
                    setActive(i);
                    setEngaged(true);
                  }}
                  onClick={() => pick(row)}
                  className="relative z-10 flex h-9 w-full items-center gap-2.5 rounded-[6px] px-2 text-left"
                >
                  {source && (
                    <span className="flex size-5.5 shrink-0 items-center justify-center text-ink-2">
                      <Icon size={15}>{GLYPHS[source.icon ?? "clip"]}</Icon>
                    </span>
                  )}
                  <span className="shrink-0 text-[12.5px] font-medium text-ink">{row.name}</span>
                  <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3">{row.desc}</span>
                </button>
              );
            })}
            {rows.length === 0 && (
              <div className="flex h-9 items-center px-2 text-[12px] text-ink-3">
                “{query}” bo‘yicha topilmadi
              </div>
            )}
            <div className="mt-1 border-t border-line px-2 pt-1.5 pb-1 text-[11px] text-ink-3">
              {menu === "at" ? "Manba yoki fayl qidiring" : "Buyruq qidiring"}
            </div>
          </div>
        )}

        {/* ── picker menu ────────────────────────────────── */}
        {picker && (
          <div
            onMouseLeave={() => setPickerHovered(null)}
            className="absolute z-10 w-44 rounded-[10px] bg-surface p-1 shadow-raised"
            style={{
              left: pickerMenuLeft,
              bottom: pickerMenuBottom,
              animation: "pop-in 180ms cubic-bezier(0.23,1,0.32,1) both",
              transformOrigin: "bottom left",
            }}
          >
            {/* single gliding highlight — floats to the hovered / selected row */}
            <span
              aria-hidden
              className="pointer-events-none absolute inset-x-1 rounded-[6px] bg-hover"
              style={{
                top: pickerBox?.top ?? 0,
                height: pickerBox?.height ?? 0,
                opacity: pickerBox && pickerHovered !== null ? 1 : 0,
                transition:
                  "top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease",
              }}
            />
            {picker.options.map((option, i) => (
              <button
                key={option.key}
                type="button"
                ref={(el) => {
                  pickerRowRefs.current[i] = el;
                }}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setPickerHovered(i)}
                onClick={() => {
                  picker.onChange(option.key);
                  setOpenPicker(null);
                  inputRef.current?.focus();
                }}
                className="relative z-10 flex h-7.5 w-full items-center gap-2 rounded-[6px] px-2 text-left"
              >
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-ink">
                  {option.name}
                </span>
                {option.tag && <span className="shrink-0 text-[11px] text-ink-3">{option.tag}</span>}
                <span className={`shrink-0 text-ink ${option.key === picker.value ? "" : "invisible"}`}>
                  <Icon size={13} strokeWidth={2.5}>
                    <path d="M20 6L9 17l-5-5" />
                  </Icon>
                </span>
              </button>
            ))}
          </div>
        )}

        {/* ── composer ───────────────────────────────────── */}
        <div
          className={`relative isolate flex flex-col overflow-hidden border border-line bg-surface shadow-card transition-[border-color,border-radius] duration-150 focus-within:border-line-strong ${
            tall ? "gap-2.5 p-3.5" : "gap-1.5 p-1.5"
          } ${
            pill
              ? attachments.length > 0 || wide
                ? "rounded-[24px]"
                : "rounded-full"
              : tall
                ? "rounded-[22px]"
                : "rounded-[14px]"
          }`}
        >
          <span
            ref={measureRef}
            aria-hidden="true"
            className="pointer-events-none absolute invisible whitespace-pre text-[13px] leading-[18px]"
          >
            {value}
          </span>

          {attachments.length > 0 && (
            <div className={`flex flex-wrap gap-1.5 pt-0.5 ${pill ? "px-1" : "px-0.5"}`}>
              {attachments.map((file, i) => (
                <span
                  key={`${file}-${i}`}
                  className={`flex h-6.5 items-center gap-1.5 bg-field py-1 pr-1 pl-1.5 text-[11.5px] text-ink-2 shadow-hairline ${
                    pill ? "rounded-full" : "rounded-chip"
                  }`}
                  style={{ animation: "pop-in 200ms cubic-bezier(0.23,1,0.32,1) both" }}
                >
                  <Icon size={12}>{GLYPHS.file}</Icon>
                  <span className="max-w-36 truncate">{file}</span>
                  <button
                    type="button"
                    aria-label={`${file} — o‘chirish`}
                    onClick={() => onRemoveAttachment?.(i)}
                    className={`-my-1 flex size-6 items-center justify-center text-ink-3 transition-colors duration-100 hover:bg-line/70 hover:text-ink ${
                      pill ? "rounded-full" : "rounded-[5px]"
                    }`}
                  >
                    <Icon size={10} strokeWidth={2.5}>
                      <path d="M18 6L6 18M6 6l12 12" />
                    </Icon>
                  </button>
                </span>
              ))}
            </div>
          )}

          <div
            ref={controlsRef}
            className={`grid items-end gap-x-1 gap-y-1.5 ${
              wide
                ? "grid-cols-[28px_auto_minmax(0,1fr)_28px]"
                : "grid-cols-[28px_minmax(0,1fr)_auto_28px]"
            }`}
          >
            <button
              type="button"
              aria-label="Manba va fayl qo‘shish"
              aria-expanded={plusOpen}
              onClick={() => {
                setOpenPicker(null);
                setPlusOpen((current) => !current);
                inputRef.current?.focus();
              }}
              className={`flex size-7 shrink-0 items-center justify-center justify-self-start text-ink-3 transition-[background-color,color,transform] duration-150 hover:bg-hover hover:text-ink active:scale-[0.94] ${
                pill ? "rounded-full" : "rounded-[8px]"
              } ${plusOpen ? "bg-hover text-ink" : ""} ${wide ? "col-start-1 row-start-2" : "col-start-1 row-start-1"}`}
            >
              <Icon size={16} strokeWidth={2}>
                <path d="M12 5v14M5 12h14" />
              </Icon>
            </button>

            <textarea
              ref={inputRef}
              rows={1}
              value={value}
              maxLength={maxLength}
              disabled={disabled}
              onChange={(event) => {
                onChange(event.target.value);
                setDismissed(false);
                setPlusOpen(false);
              }}
              onKeyDown={(event) => {
                if (menu && rows.length > 0) {
                  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                    event.preventDefault();
                    setEngaged(true);
                    setActive(
                      (current) =>
                        (current + (event.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length,
                    );
                    return;
                  }
                  if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
                    event.preventDefault();
                    pick(rows[active]);
                    return;
                  }
                }
                if (event.key === "Escape") {
                  setDismissed(true);
                  closeMenus();
                  return;
                }
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  send();
                }
              }}
              placeholder={placeholder ?? "Xabar yozing…"}
              aria-label="Buyruq"
              className={`${tall ? "min-h-[68px] px-2 py-2 text-[14px] leading-5" : "min-h-7 px-1 py-[5px] text-[13px] leading-[18px]"} min-w-0 w-full resize-none bg-transparent text-ink outline-none [overflow-wrap:anywhere] placeholder:text-ink-3 ${
                wide ? "col-span-full col-start-1 row-start-1" : "col-start-2 row-start-1"
              }`}
            />

            {/* pickers — one measurement path, N triggers */}
            <div
              ref={pickersRef}
              className={`flex shrink-0 items-center gap-1 ${
                wide ? "col-start-2 row-start-2 justify-self-start" : "col-start-3 row-start-1"
              }`}
            >
              {pickers.map((entry) => {
                const selected = entry.options.find((o) => o.key === entry.value);
                return (
                  <button
                    key={entry.key}
                    ref={(el) => {
                      pickerBtnRefs.current[entry.key] = el;
                    }}
                    type="button"
                    aria-expanded={openPicker === entry.key}
                    aria-label={entry.label}
                    onClick={() => {
                      setPlusOpen(false);
                      setOpenPicker((current) => (current === entry.key ? null : entry.key));
                    }}
                    className={`flex h-7 shrink-0 items-center gap-1 px-1.5 text-[12px] font-medium text-ink-2 transition-colors duration-150 hover:bg-hover hover:text-ink ${
                      pill ? "rounded-full" : "rounded-[8px]"
                    }`}
                  >
                    {selected?.name ?? entry.label}
                    <span className="text-ink-3">
                      <Icon size={11} strokeWidth={2.4}>
                        <path d="M6 9l6 6 6-6" />
                      </Icon>
                    </span>
                  </button>
                );
              })}
            </div>

            {/* send — tactile square (round in the pill variant) */}
            <button
              type="button"
              aria-label="Yuborish"
              disabled={!canSend}
              onClick={send}
              className={`flex size-7 shrink-0 items-center justify-center transition-[background-color,color,transform] duration-200 enabled:active:scale-[0.94] ${
                pill ? "rounded-full" : "rounded-[8px]"
              } ${wide ? "col-start-4 row-start-2" : "col-start-4 row-start-1"}`}
              style={{
                background: canSend ? "var(--ink)" : "var(--line-strong)",
                color: canSend ? "var(--surface)" : "var(--ink-2)",
              }}
            >
              {busy ? (
                <span
                  aria-hidden
                  className="size-3.5 rounded-full border-[1.5px] border-current border-t-transparent"
                  style={{ animation: "spin 700ms linear infinite" }}
                />
              ) : (
                <Icon size={16} strokeWidth={2.4}>
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </Icon>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default PromptBar;
