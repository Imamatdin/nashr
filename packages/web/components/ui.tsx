"use client";

// Shared presentational pieces of the app. Purely visual — no data fetching,
// no auth; pages own their state and pass it down.

import type { LucideIcon } from "lucide-react";
import type { ComponentPropsWithoutRef, ReactNode, RefObject } from "react";
import { useEffect, useState } from "react";

type ButtonVariant = "primary" | "ghost" | "danger";
type ButtonSize = "md" | "lg";

type ButtonProps = Omit<ComponentPropsWithoutRef<"button">, "className"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Inert. Kept so the not-yet-rebuilt views still type-check. */
  gilded?: boolean;
  loading?: boolean;
  block?: boolean;
  className?: string;
};

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "btn-primary",
  ghost: "btn-ghost",
  danger: "btn-danger",
};

function DotPulse() {
  return (
    <span className="btn-pulse" aria-hidden>
      <i />
      <i />
      <i />
    </span>
  );
}

export function Button({
  variant = "primary",
  size = "md",
  gilded: _gilded = false,
  loading = false,
  block = false,
  className,
  disabled,
  type = "button",
  children,
  ...rest
}: ButtonProps) {
  const classes = [
    "btn",
    VARIANT_CLASS[variant],
    size === "lg" ? "btn-lg" : null,
    block ? "btn-block" : null,
    loading ? "btn-loading" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      {...rest}
      type={type}
      className={classes}
      disabled={disabled === true || loading}
      aria-busy={loading || undefined}
    >
      <span className="btn-label">{children}</span>
      {loading && <DotPulse />}
    </button>
  );
}

/**
 * Machine facts — prices, credit counts, ids. Mono with tabular figures so a
 * changing number never reflows the line around it.
 */
export function DataText({
  children,
  className,
  ...rest
}: ComponentPropsWithoutRef<"span"> & { className?: string }) {
  return (
    <span {...rest} className={className ? `data-text ${className}` : "data-text"}>
      {children}
    </span>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  hint,
  children,
}: {
  icon?: LucideIcon;
  title: string;
  hint: string;
  children?: ReactNode;
}) {
  return (
    <div className="state state-blank">
      {Icon && (
        <span className="state-icon" aria-hidden>
          <Icon size={18} strokeWidth={1.75} />
        </span>
      )}
      <h3>{title}</h3>
      <p>{hint}</p>
      {children}
    </div>
  );
}

export function ErrorState({
  title = "Nimadir xato ketdi",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state state-note" role="alert">
      <h3>{title}</h3>
      <p>{message}</p>
      {onRetry && (
        <Button variant="ghost" onClick={onRetry}>
          Qayta urinish
        </Button>
      )}
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-busy="true" aria-label="Yuklanmoqda">
      {Array.from({ length: lines }, (_, index) => (
        <div
          key={index}
          className="skeleton"
          style={{ height: "1.1rem", marginBottom: "0.8rem", width: `${100 - index * 12}%` }}
        />
      ))}
    </div>
  );
}

export function Toast({ message, danger }: { message: string; danger?: boolean }) {
  return (
    <div className={danger ? "toast toast-danger" : "toast"} role="status">
      {message}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = {
    draft: "Qoralama",
    sourcing: "Manbalar",
    interview: "Suhbat",
    generating: "Yaratilmoqda",
    ready: "Tayyor",
    failed: "Xatolik",
    archived: "Arxiv",
    queued: "Navbatda",
    processing: "Jarayonda",
    completed: "Tayyor",
    cancelled: "Bekor qilingan",
  };
  const cls =
    status === "ready" || status === "completed"
      ? "badge badge-ok"
      : status === "failed" || status === "cancelled"
        ? "badge badge-danger"
        : status === "generating" || status === "processing" || status === "queued"
          ? "badge badge-busy"
          : "badge";
  return <span className={cls}>{label[status] ?? status}</span>;
}

/**
 * The upload control. A native file input renders the browser's own
 * "Choose File / No file chosen" plate, which no amount of surrounding craft
 * survives — so the input is visually hidden (never display:none: it keeps its
 * id/name/autocomplete and its place in the tab order) and a label drives it.
 */
export function FileField({
  inputRef,
  id,
  name,
  accept,
  multiple,
  disabled,
  clearSignal = 0,
  label,
  hint,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  id: string;
  name: string;
  accept: string;
  multiple?: boolean;
  disabled?: boolean;
  /** Bump to drop the chosen-file line after the parent clears the input. */
  clearSignal?: number;
  label: string;
  hint: string;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  useEffect(() => setPicked([]), [clearSignal]);

  return (
    <div className="filefield">
      <input
        ref={inputRef}
        id={id}
        name={name}
        className="filefield-input"
        type="file"
        autoComplete="off"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={(event) =>
          setPicked(Array.from(event.target.files ?? []).map((file) => file.name))
        }
      />
      <label htmlFor={id} className="filefield-drop" data-disabled={disabled ? "true" : undefined}>
        <span className="filefield-label">{label}</span>
        <span className="filefield-hint">{hint}</span>
      </label>
      <p className="filefield-picked">
        {picked.length === 0 ? (
          " "
        ) : picked.length === 1 ? (
          picked[0]
        ) : (
          <>
            <DataText>{picked.length}</DataText> ta fayl tanlandi
          </>
        )}
      </p>
    </div>
  );
}

export function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}
