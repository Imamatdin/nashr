import { describe, expect, it } from "vitest";
import type { DeckAccessView, ExportLinks } from "./api";
import { shownExports } from "./deck-exports";

const links = (revision: string): ExportLinks => ({
  revision_id: revision,
  renderer_version: "pw-1",
  created_at: "2026-10-11T00:00:00Z",
  html_url: `https://r2/${revision}.html`,
  html_expires_in: 900,
  downloads: [],
});

const base: DeckAccessView = {
  revision_id: "head",
  head_revision_id: "head",
  is_head: true,
  state: "ready",
  renderer_version: "pw-1",
  current: links("head"),
  fallback: null,
};

describe("shownExports never passes an older export off as the current one", () => {
  it("shows the head's own exports without a notice", () => {
    expect(shownExports(base)).toEqual({ exports: links("head"), notice: null });
  });

  it("says a render is needed when nothing exists", () => {
    const deck = { ...base, state: "render_needed" as const, current: null };
    expect(shownExports(deck)).toEqual({ exports: null, notice: "renderNeeded" });
  });

  it("labels an earlier version's export", () => {
    const deck = {
      ...base,
      state: "render_needed" as const,
      current: null,
      fallback: { ...links("older"), reason: "older_revision" as const },
    };
    const shown = shownExports(deck);
    expect(shown.notice).toBe("olderRevision");
    expect(shown.exports?.revision_id).toBe("older");
  });

  it("labels the same version from an earlier renderer", () => {
    const deck = {
      ...base,
      state: "render_needed" as const,
      current: null,
      fallback: { ...links("head"), reason: "older_renderer" as const },
    };
    expect(shownExports(deck).notice).toBe("olderRenderer");
  });
});
