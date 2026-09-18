import { describe, expect, it } from "vitest";
import { resolveLocale, creationHref } from "./locale";
import { sanitizeReturnTo } from "./return-to";

describe("workspace language", () => {
  it("prefers an explicit choice over browser language", () => {
    expect(resolveLocale("ru", "en-US")).toBe("ru");
    expect(resolveLocale(null, "uz-Latn")).toBe("uz");
    expect(resolveLocale("invalid", "ru-RU")).toBe("ru");
  });
  it("carries a Russian brief and chosen language through sign-in", () => {
    const href = creationHref("ru", "Исследование образования ".repeat(25));
    const target = new URL(href, "https://example.test").searchParams.get("returnTo")!;
    expect(sanitizeReturnTo(target)).toBe(target);
    expect(new URL(target, "https://example.test").searchParams.get("lang")).toBe("ru");
    expect(new URL(target, "https://example.test").searchParams.get("topic")).toContain("Исследование");
  });
});
