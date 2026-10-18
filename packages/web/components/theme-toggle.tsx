"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import { useLocale } from "@/components/locale-provider";
import type { ThemePreference } from "@/lib/theme";

const OPTIONS: ReadonlyArray<{
  value: ThemePreference;
  Icon: typeof Monitor;
}> = [
  { value: "system", Icon: Monitor },
  { value: "light", Icon: Sun },
  { value: "dark", Icon: Moon },
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
  const { locale } = useLocale();
  const copy = {
    en: { group: "Theme", system: "System", light: "Light", dark: "Dark" },
    ru: { group: "Тема", system: "Система", light: "Светлая", dark: "Тёмная" },
    uz: { group: "Mavzu", system: "Tizim", light: "Yorug‘", dark: "Qorong‘i" },
    kaa: { group: "Tema", system: "Sistema", light: "Jaqtı", dark: "Qarańǵı" },
  }[locale];

  return (
    <div
      role="group"
      aria-label={copy.group}
      className={`flex items-center gap-0.5 rounded-control bg-inset p-0.5 ${
        vertical ? "flex-col" : ""
      }`}
    >
      {OPTIONS.map(({ value, Icon }) => {
        const label = copy[value];
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
