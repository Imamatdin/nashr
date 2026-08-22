// Theme resolution, DOM-free so it can be unit-tested. The landing (pathname
// "/") is permanently light: it is the only page whose ground is a brand
// decision rather than a user preference.

export type Theme = "light" | "dark";
export type ThemePreference = Theme | "system";

export const STORAGE_KEY = "nashr.theme";

export function readPreference(raw: string | null): ThemePreference {
  return raw === "dark" || raw === "light" ? raw : "system";
}

export function resolveTheme(
  preference: ThemePreference,
  systemDark: boolean,
  pathname: string,
): Theme {
  if (pathname === "/") return "light";
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}

export const NO_FLASH_SCRIPT = `(function(){try{
var raw=window.localStorage.getItem(${JSON.stringify(STORAGE_KEY)});
var pref=(raw==="dark"||raw==="light")?raw:"system";
var systemDark=window.matchMedia("(prefers-color-scheme: dark)").matches;
var dark=window.location.pathname!=="/"&&(pref==="dark"||(pref==="system"&&systemDark));
document.documentElement.classList[dark?"add":"remove"]("dark");
}catch(e){}})();`;
