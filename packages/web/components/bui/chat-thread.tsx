"use client";

/* ─────────────────────────────────────────────────────────
 * CHAT THREAD — the conversation spine of the workspace (bui #07)
 *
 * The audit's B2 bar: "conversation is the spine". Nashr had zero chat on web;
 * the only typed input anywhere was a 200-char title field the pipeline never
 * received. The whole Way-2 editing engine existed bot-side.
 *
 * This is deliberately NOT a chat app. It renders a persisted thread, a
 * composer, and — inline, in thread order — the two things a turn can produce
 * besides text: an approval card for a change the model proposed on its own,
 * and a live task row while an edit job re-renders the deck.
 *
 * Deck-wide instructions are just messages (the Gamma agent-edit pattern), so
 * there is no separate "edit mode" UI to get out of sync.
 * ───────────────────────────────────────────────────────── */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUp, Check, X } from "lucide-react";

export interface ChatThreadMessage {
  key: string;
  role: "user" | "assistant";
  text: string;
  /** Renders quieter, for a turn that is still settling. */
  pending?: boolean;
}

export interface ChatPendingDecision {
  reason: string;
  fixes: Array<{ slide_id: string; instruction: string }>;
}

export interface ChatThreadProps {
  messages: ChatThreadMessage[];
  /** Composer text — controlled so the page can clear it on send. */
  value: string;
  onChange: (next: string) => void;
  onSend: () => void;
  /** A turn is in flight; the composer is held but the thread stays readable. */
  busy?: boolean;
  /**
   * Editing is impossible (no deck yet). The composer is replaced by an honest
   * explanation rather than being silently inert.
   */
  disabledReason?: string | null;
  placeholder?: string;
  /** Parked change awaiting the user's button — never the model's own say-so. */
  pending?: ChatPendingDecision | null;
  onApprove?: () => void;
  onReject?: () => void;
  approving?: boolean;
  /** Rendered under the thread: progress while an edit job runs. */
  applying?: ReactNode;
  /** Rendered above the composer: allowance, errors, hints. */
  footer?: ReactNode;
}

export function ChatThread({
  messages,
  value,
  onChange,
  onSend,
  busy = false,
  disabledReason = null,
  placeholder = "Nimani o‘zgartiramiz?",
  pending = null,
  onApprove,
  onReject,
  approving = false,
  applying,
  footer,
}: ChatThreadProps) {
  const scroller = useRef<HTMLDivElement | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const [atBottom, setAtBottom] = useState(true);

  // Follow the conversation only when the reader is already at the bottom —
  // yanking someone away from a message they are re-reading is worse than a
  // missed autoscroll.
  useEffect(() => {
    if (!atBottom) return;
    const node = scroller.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, pending, applying, atBottom]);

  useEffect(() => {
    const node = box.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 160)}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !busy && !disabledReason;

  return (
    <div className="chat" data-busy={busy ? "true" : undefined}>
      <div
        className="chat-scroll"
        ref={scroller}
        onScroll={(event) => {
          const node = event.currentTarget;
          setAtBottom(node.scrollHeight - node.scrollTop - node.clientHeight < 48);
        }}
      >
        {messages.length === 0 && !pending && (
          <div className="chat-blank">
            <p className="chat-blank-title">Taqdimot ustida gaplashamiz</p>
            <p className="chat-blank-hint">
              «3-slayddagi sanani to‘g‘rila» yoki «xulosani qisqartir» deb yozing. Nashr faqat
              siz yuklagan manbalardagi faktlarga tayanadi.
            </p>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.key}
            className="chat-msg"
            data-role={message.role}
            data-pending={message.pending ? "true" : undefined}
          >
            <div className="chat-bubble">{message.text}</div>
          </div>
        ))}

        {pending && (
          <div className="chat-approval" role="group" aria-label="Tasdiqlash">
            <p className="chat-approval-title">Bu o‘zgarishni qo‘llaymizmi?</p>
            {pending.reason && <p className="chat-approval-reason">{pending.reason}</p>}
            <ul className="chat-approval-fixes">
              {pending.fixes.map((fix, index) => (
                <li key={`${fix.slide_id}-${index}`}>
                  <span className="chat-approval-slide data-text">{fix.slide_id}</span>
                  <span>{fix.instruction}</span>
                </li>
              ))}
            </ul>
            <div className="chat-approval-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={onApprove}
                disabled={approving}
                aria-busy={approving || undefined}
              >
                <span className="btn-label">
                  <Check size={15} strokeWidth={2} aria-hidden /> Qo‘llash
                </span>
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={onReject}
                disabled={approving}
              >
                <span className="btn-label">
                  <X size={15} strokeWidth={2} aria-hidden /> Kerak emas
                </span>
              </button>
            </div>
          </div>
        )}

        {applying && <div className="chat-applying">{applying}</div>}
      </div>

      {footer && <div className="chat-footer">{footer}</div>}

      {disabledReason ? (
        <p className="chat-disabled">{disabledReason}</p>
      ) : (
        <div className="chat-composer" data-promptbar>
          <textarea
            ref={box}
            className="chat-input"
            value={value}
            rows={1}
            placeholder={placeholder}
            aria-label="Xabar"
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (canSend) onSend();
              }
            }}
          />
          <button
            type="button"
            className="chat-send"
            onClick={onSend}
            disabled={!canSend}
            aria-label="Yuborish"
          >
            <ArrowUp size={16} strokeWidth={2.25} aria-hidden />
          </button>
        </div>
      )}
    </div>
  );
}

export default ChatThread;
