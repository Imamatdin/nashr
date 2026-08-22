"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import type { ThemePreference } from "@/lib/theme";

const OPTIONS: ReadonlyArray<{
  value: ThemePreference;
  label: string;
  Icon: typeof Monitor;
}> = [
  { value: "system", label: "Tizim", Icon: Monitor },
  { value: "light", label: "Yorug‘", Icon: Sun },
  { value: "dark", label: "Qorong‘i", Icon: Moon },
];

export function ThemeToggle({
  compact = false,
  vertical = false,
}: {
  /** Icon only: the collapsed rail and the phone topbar. */
  compact?: boolean;
  vertical?: boolean;
}) {
  const { theme, setTheme } = useTheme();

  return (
    <div
      role="group"
      aria-label="Mavzu"
      className={`flex items-center gap-0.5 rounded-control bg-inset p-0.5 ${
        vertical ? "flex-col" : ""
      }`}
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = theme === value;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={active}
            aria-label={label}
            title={label}
            onClick={() => setTheme(value)}
            className={`flex items-center justify-center gap-1 rounded-chip text-[11.5px] font-medium transition-[background-color,color] duration-150 ${
              compact ? "size-7" : "h-7 flex-1 px-1.5"
            } ${active ? "bg-surface text-ink shadow-btn" : "text-ink-3 hover:text-ink"}`}
          >
            {compact ? (
              <Icon size={14} strokeWidth={1.75} aria-hidden />
            ) : (
              <span className="truncate">{label}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
