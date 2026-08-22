"use client";

import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  readPreference,
  resolveTheme,
  STORAGE_KEY,
  type Theme,
  type ThemePreference,
} from "@/lib/theme";

type ThemeContextValue = {
  theme: ThemePreference;
  resolved: Theme;
  setTheme: (preference: ThemePreference) => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  theme: "system",
  resolved: "light",
  setTheme: () => {},
});

const MEDIA = "(prefers-color-scheme: dark)";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [theme, setThemeState] = useState<ThemePreference>("system");
  const [systemDark, setSystemDark] = useState(false);
  // Until the stored preference and the media state are read, this component
  // knows less than the inline no-flash script already applied to <html>.
  // Touching the class before then strips it and flashes light after hydration.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setThemeState(readPreference(window.localStorage.getItem(STORAGE_KEY)));
    setSystemDark(window.matchMedia(MEDIA).matches);
    setReady(true);
  }, []);

  useEffect(() => {
    if (theme !== "system") return;
    const query = window.matchMedia(MEDIA);
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [theme]);

  const resolved = resolveTheme(theme, systemDark, pathname ?? "/");

  useEffect(() => {
    if (!ready) return;
    document.documentElement.classList.toggle("dark", resolved === "dark");
  }, [ready, resolved]);

  const setTheme = useCallback((preference: ThemePreference) => {
    setThemeState(preference);
    try {
      if (preference === "system") window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      // Private-mode storage denial must not break the toggle for this session.
    }
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, resolved, setTheme }),
    [theme, resolved, setTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
