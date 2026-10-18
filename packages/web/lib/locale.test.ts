import { describe, expect, it } from "vitest";
import { LOCALE_NAMES, LOCALES, resolveLocale, creationHref } from "./locale";
import { sanitizeReturnTo } from "./return-to";

describe("workspace language", () => {
  it("prefers an explicit choice over browser language", () => {
    expect(resolveLocale("ru", "en-US")).toBe("ru");
    expect(resolveLocale(null, "uz-Latn")).toBe("uz");
    expect(resolveLocale("invalid", "ru-RU")).toBe("ru");
  });
  it("supports Karakalpak as an equal fourth locale", () => {
    expect(LOCALES).toContain("kaa");
    expect(LOCALE_NAMES.kaa).toBe("Qaraqalpaqsha");
    expect(resolveLocale("kaa", "ru-RU")).toBe("kaa");
    expect(resolveLocale(null, "kaa-UZ")).toBe("kaa");
  });
  it("carries a Russian brief and chosen language through sign-in", () => {
    const href = creationHref("ru", "Исследование образования ".repeat(25));
    const target = new URL(href, "https://example.test").searchParams.get("returnTo")!;
    expect(sanitizeReturnTo(target)).toBe(target);
    expect(new URL(target, "https://example.test").searchParams.get("lang")).toBe("ru");
    expect(new URL(target, "https://example.test").searchParams.get("topic")).toContain("Исследование");
  });
});
