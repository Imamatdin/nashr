"use client";

import { useState, type ReactNode } from "react";

/* ─────────────────────────────────────────────────────────
 * APPROVAL CARD (human-in-the-loop)
 * One question at a time; elongated pills show progress;
 * the circular arrow up top advances (↑ sends on the last).
 * Choices, paging, and submission are directly controlled.
 * ───────────────────────────────────────────────────────── */

// Ported from beautifului.dev "approval-card" (MIT). Kept: qi / answers / custom state, the 480ms
// radio auto-advance that auto-sends on the last question, the ring-dot pager with its width/height
// transition, prev/next, the send arrow's ink/field state swap, the sent badge pop-in, and the
// per-question fade-up.
// Replaced: the QUESTIONS fixture -> `questions` prop; onSubmitted now receives the collected
// answers; the custom free-text row is gated behind `allowCustom` and the dismiss control behind
// `dismissible`; `summary` renders above the question inside the card.

export interface ApprovalOption {
  label: string;
  hint?: string;
}

export interface ApprovalQuestion {
  q: string;
  type: "radio" | "check";
  options: ApprovalOption[];
}

export interface ApprovalAnswer {
  question: string;
  selected: string[];
  custom?: string;
}

export interface ApprovalCardProps {
  questions: ApprovalQuestion[];
  initial?: Record<number, number[]>;
  summary?: ReactNode;
  onSubmitted?: (answers: ApprovalAnswer[]) => void;
  sentLabel?: string;
  resetLabel?: string;
  allowCustom?: boolean;
  dismissible?: boolean;
}

function collect(
  questions: ApprovalQuestion[],
  answers: Record<number, number[]>,
  custom: Record<number, string>,
): ApprovalAnswer[] {
  return questions.map((question, index) => ({
    question: question.q,
    selected: (answers[index] ?? []).map((i) => question.options[i]?.label ?? ""),
    custom: custom[index]?.trim() ? custom[index].trim() : undefined,
  }));
}

export function ApprovalCard({
  questions,
  initial,
  summary,
  onSubmitted,
  sentLabel = "Tasdiqlandi",
  resetLabel,
  allowCustom = false,
  dismissible = false,
}: ApprovalCardProps) {
  const [qi, setQi] = useState(0);
  const [answers, setAnswers] = useState<Record<number, number[]>>(initial ?? {});
  const [custom, setCustom] = useState<Record<number, string>>({});
  const [sent, setSent] = useState(false);
  const [open, setOpen] = useState(true);
  const question = questions[qi];
  const last = qi === questions.length - 1;
  const selected = answers[qi] ?? [];
  const hasAnswer = selected.length > 0 || Boolean(custom[qi]?.trim());

  const toggle = (index: number) => {
    const picked = answers[qi] ?? [];
    const nextPicked =
      question.type === "radio"
        ? [index]
        : picked.includes(index)
          ? picked.filter((item) => item !== index)
          : [...picked, index];
    const nextAnswers = { ...answers, [qi]: nextPicked };
    setAnswers(nextAnswers);
    if (question.type === "radio") {
      const nextCustom = { ...custom, [qi]: "" };
      setCustom(nextCustom);
      // single-choice auto-advances
      window.setTimeout(() => {
        if (qi === questions.length - 1) {
          setSent(true);
          onSubmitted?.(collect(questions, nextAnswers, nextCustom));
        } else setQi((current) => Math.min(questions.length - 1, current + 1));
      }, 480);
    }
  };

  const reset = () => {
    setQi(0);
    setAnswers(initial ?? {});
    setCustom({});
    setSent(false);
    setOpen(true);
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-control bg-surface px-3 py-2 text-[12.5px] font-medium text-ink shadow-btn transition-colors duration-150 hover:bg-hover"
      >
        Savollarni ochish
      </button>
    );
  }

  // Once answered, the whole card fires off into a small confirmation badge.
  if (sent) {
    return (
      <div
        className="flex w-full max-w-80 items-center gap-3"
        style={{ animation: "pop-in 260ms cubic-bezier(0.23,1,0.32,1) both" }}
      >
        <span className="inline-flex items-center gap-1.5 rounded-full bg-green-tint py-1 pr-2.5 pl-1 text-[12.5px] font-medium text-green">
          <span className="flex size-4.5 items-center justify-center rounded-full bg-green text-on-accent">
            <svg
              width="11"
              height="11"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M20 6L9 17l-5-5" />
            </svg>
          </span>
          {sentLabel}
        </span>
        {resetLabel && (
          <button
            type="button"
            onClick={reset}
            className="text-[12px] font-medium text-ink-3 transition-colors duration-150 hover:text-ink"
          >
            {resetLabel}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex w-full max-w-80 flex-col items-stretch">
      <div className="w-full self-start overflow-hidden rounded-card bg-surface shadow-card">
        <div
          key={qi}
          className="primitive-card-pad"
          style={{ animation: "fade-up 350ms cubic-bezier(0.23,1,0.32,1) both" }}
        >
          {summary && <div className="mb-2 text-[12px] leading-relaxed text-ink-2">{summary}</div>}
          <div className="flex items-start justify-between gap-3">
            <span className="text-[13px] font-medium text-ink">{question.q}</span>
            {dismissible && (
              <button
                type="button"
                aria-label="Yopish"
                onClick={() => setOpen(false)}
                className="primitive-icon-button shrink-0
                  text-ink-3 transition-colors duration-100 hover:bg-hover hover:text-ink"
              >
                <svg
                  width="14"
                  height="14"
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
          <div className="mt-2 flex flex-col gap-0.5">
            {question.options.map((option, i) => {
              const on = selected.includes(i);
              return (
                <button
                  key={option.label}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(i)}
                  className="-mx-1.5 flex items-center gap-2 rounded-control px-1.5 py-1 text-left transition-colors duration-100 hover:bg-hover"
                >
                  <span
                    className={`flex size-4 shrink-0 items-center justify-center transition-colors duration-200
                        ${question.type === "radio" ? "rounded-full" : "rounded-[5px]"}
                        ${on ? "bg-ink text-canvas" : "shadow-[inset_0_0_0_1.5px_var(--line-strong)] text-transparent"}`}
                  >
                    {question.type === "radio" ? (
                      <span
                        className="size-1.5 rounded-full bg-canvas transition-transform duration-200"
                        style={{ transform: on ? "scale(1)" : "scale(0)" }}
                      />
                    ) : (
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
                        <path d="M20 6L9 17l-5-5" />
                      </svg>
                    )}
                  </span>
                  <span className="min-w-0">
                    <span
                      className={`block text-[13px] transition-colors duration-200 ${on ? "text-ink" : "text-ink-2"}`}
                    >
                      {option.label}
                    </span>
                    {option.hint && (
                      <span className="block text-[11.5px] text-ink-3">{option.hint}</span>
                    )}
                  </span>
                </button>
              );
            })}
            {allowCustom && (
              <label className="-mx-1.5 flex items-center gap-2 rounded-control px-1.5 py-1 transition-colors duration-100 focus-within:bg-hover hover:bg-hover">
                <span aria-hidden="true" className="size-4 shrink-0" />
                <input
                  value={custom[qi] ?? ""}
                  onChange={(event) => {
                    setCustom((current) => ({ ...current, [qi]: event.target.value }));
                    if (question.type === "radio")
                      setAnswers((current) => ({ ...current, [qi]: [] }));
                  }}
                  placeholder="O‘z javobingiz…"
                  aria-label="O‘z javobingiz"
                  className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3"
                />
              </label>
            )}
          </div>
        </div>

        {/* footer — ring-dot pager + send arrow */}
        <div className="primitive-card-footer flex items-center justify-between">
          <span className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Orqaga"
              disabled={qi === 0 || sent}
              onClick={() => setQi((current) => Math.max(0, current - 1))}
              className="flex size-6 items-center justify-center rounded-[5px] text-ink-3 transition-colors duration-100 enabled:hover:bg-hover enabled:hover:text-ink-2 disabled:opacity-35"
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M15 18l-6-6 6-6" />
              </svg>
            </button>
            <span className="flex items-center gap-1">
              {questions.map((_, i) => (
                <button
                  key={i}
                  type="button"
                  aria-label={`${i + 1}-savolga o‘tish`}
                  aria-current={i === qi && !sent ? "step" : undefined}
                  disabled={sent}
                  onClick={() => setQi(i)}
                  className="rounded-full transition-[width,height,background-color,border-color,border-width] duration-300 disabled:cursor-default"
                  style={
                    i === qi && !sent
                      ? { width: 9, height: 9, border: "2.5px solid var(--ink)" }
                      : sent || i < qi
                        ? { width: 7, height: 7, background: "var(--ink-3)" }
                        : { width: 7, height: 7, border: "1.5px solid var(--ink-3)" }
                  }
                />
              ))}
            </span>
            <button
              type="button"
              aria-label="Keyingisi"
              disabled={last || sent}
              onClick={() => setQi((current) => Math.min(questions.length - 1, current + 1))}
              className="flex size-6 items-center justify-center rounded-[5px] text-ink-3 transition-colors duration-100 enabled:hover:bg-hover enabled:hover:text-ink-2 disabled:opacity-35"
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M9 6l6 6-6 6" />
              </svg>
            </button>
          </span>
          {!sent && (
            <button
              type="button"
              aria-label={last ? "Javoblarni yuborish" : "Keyingi savol"}
              disabled={!hasAnswer}
              onClick={() => {
                if (last) {
                  setSent(true);
                  onSubmitted?.(collect(questions, answers, custom));
                } else {
                  setQi((current) => current + 1);
                }
              }}
              className="-mr-0.5 flex size-7 items-center justify-center rounded-[8px] transition-[background-color,color,transform] duration-200 enabled:active:scale-[0.96]"
              style={{
                background: hasAnswer ? "var(--ink)" : "var(--field)",
                color: hasAnswer ? "var(--surface)" : "var(--ink-3)",
                boxShadow: hasAnswer ? "inset 0 1px 0 rgba(255,255,255,0.14)" : "var(--shadow-btn)",
              }}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default ApprovalCard;
