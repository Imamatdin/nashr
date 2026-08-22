import { describe, expect, it } from "vitest";
import { NO_FLASH_SCRIPT, readPreference, resolveTheme, STORAGE_KEY } from "./theme";

describe("readPreference", () => {
  it("accepts the two stored themes", () => {
    expect(readPreference("dark")).toBe("dark");
    expect(readPreference("light")).toBe("light");
  });

  it("treats an absent value as system", () => {
    expect(readPreference(null)).toBe("system");
  });

  it("treats an invalid stored value as system", () => {
    expect(readPreference("qorongi")).toBe("system");
    expect(readPreference("")).toBe("system");
  });
});

describe("resolveTheme", () => {
  it("lets a stored dark win over a light system", () => {
    expect(resolveTheme("dark", false, "/projects")).toBe("dark");
  });

  it("lets a stored light win over a dark system", () => {
    expect(resolveTheme("light", true, "/projects")).toBe("light");
  });

  it("follows the system when no value is stored", () => {
    expect(resolveTheme("system", true, "/projects")).toBe("dark");
    expect(resolveTheme("system", false, "/projects")).toBe("light");
  });

  it("keeps the landing light whatever is stored", () => {
    expect(resolveTheme("dark", true, "/")).toBe("light");
    expect(resolveTheme("system", true, "/")).toBe("light");
  });

  it("resolves an invalid stored value as system", () => {
    expect(resolveTheme(readPreference("nonsense"), true, "/new")).toBe("dark");
    expect(resolveTheme(readPreference("nonsense"), false, "/new")).toBe("light");
  });
});

describe("NO_FLASH_SCRIPT", () => {
  it("carries the storage key and guards the landing", () => {
    expect(NO_FLASH_SCRIPT).toContain(STORAGE_KEY);
    expect(NO_FLASH_SCRIPT).toContain('window.location.pathname!=="/"');
    expect(NO_FLASH_SCRIPT).toContain("catch");
  });
});
