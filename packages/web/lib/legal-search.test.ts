import { describe, expect, it } from "vitest";
import { lexUzSearchUrl } from "./legal-search";

describe("lexUzSearchUrl", () => {
  it("opens a localized official title search with encoded user text", () => {
    expect(lexUzSearchUrl("  ta’lim huquqi  ", "uz")).toBe(
      "https://lex.uz/uz/search/all?searchtitle=ta%E2%80%99lim+huquqi",
    );
    expect(lexUzSearchUrl("образование", "ru")).toContain(
      "https://lex.uz/ru/search/all?searchtitle=",
    );
  });

  it("uses the official homepage until Lex.uz's minimum title length is met", () => {
    expect(lexUzSearchUrl("AI", "en")).toBe("https://lex.uz/en/");
  });
});
