"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { LOCALE_KEY, LOCALE_NAMES, LOCALES, resolveLocale, type Locale } from "@/lib/locale";

const Context = createContext<{ locale: Locale; setLocale: (locale: Locale) => void }>({
  locale: "uz", setLocale: () => {},
});

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, update] = useState<Locale>("uz");
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem(LOCALE_KEY); } catch { /* Storage is optional. */ }
    const selected = resolveLocale(saved, navigator.language);
    update(selected);
    document.documentElement.lang = selected;
    const sync = (event: StorageEvent) => {
      if (event.key === LOCALE_KEY) {
        const next = resolveLocale(event.newValue, navigator.language);
        update(next);
        document.documentElement.lang = next;
      }
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  function setLocale(next: Locale) {
    update(next);
    document.documentElement.lang = next;
    try { localStorage.setItem(LOCALE_KEY, next); } catch { /* The current selection still works. */ }
  }
  return <Context.Provider value={{ locale, setLocale }}>{children}</Context.Provider>;
}

export function useLocale() { return useContext(Context); }

export function LanguagePicker() {
  const { locale, setLocale } = useLocale();
  return <select className="n-language" aria-label="O‘zbekcha / Русский / Qaraqalpaqsha / English" value={locale}
    onChange={(event) => setLocale(event.target.value as Locale)}>
    {LOCALES.map((code) => <option key={code} value={code}>{LOCALE_NAMES[code]}</option>)}
  </select>;
}
