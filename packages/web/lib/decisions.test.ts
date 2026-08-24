import { describe, expect, it } from "vitest";
import type { DecisionsView } from "./api";
import {
  audienceLabel,
  backgroundLabel,
  decidedFor,
  emphasisLabel,
  hasArgument,
  moodLabel,
  phaseLabel,
  swatches,
} from "./decisions";

function view(overrides: Partial<DecisionsView> = {}): DecisionsView {
  return {
    title: "Orol dengizi",
    language: "uz",
    thesis: "Suv olib qo'yish dengizni qisqartirdi.",
    audience_takeaway: "Tinglovchi sababni ayta oladi.",
    sections: [{ section_name: "Sabab", thesis: "Kanallar oqimni burdi.", phase: "hook" }],
    mood: "warm_historical",
    palette: {
      background: "#1A120B",
      surface: "#D4C5A9",
      text: "#F5F0E8",
      accent: "#C4923A",
      text_secondary: "#A89F91",
    },
    heading_font: "Playfair Display",
    body_font: "EB Garamond",
    background_treatment: "dark",
    image_style_prefix: "documentary photography",
    image_cohesion_note: "Bitta izchil uslub.",
    audience: "undergraduate",
    talk_duration_minutes: 15,
    narrative_emphasis: "results_numbers",
    include_interactive: true,
    slide_count: 11,
    slides: [{ slide_number: 1, slide_id: "s1", slide_type: "title_hero", title: "Ochilish" }],
    ...overrides,
  };
}

describe("machine words never reach the reader", () => {
  it("translates the enums the backend stores", () => {
    expect(moodLabel("warm_historical")).not.toBe("warm_historical");
    expect(audienceLabel("undergraduate")).not.toBe("undergraduate");
    expect(emphasisLabel("results_numbers")).not.toBe("results_numbers");
    expect(phaseLabel("hook")).not.toBe("hook");
    expect(backgroundLabel("dark")).not.toBe("dark");
  });

  it("falls back to the raw token rather than a wrong guess", () => {
    // A mood added backend-side should read oddly, not incorrectly — mapping
    // an unknown value onto some neighbouring label would be worse than plain.
    expect(moodLabel("brand_new_mood")).toBe("brand_new_mood");
    expect(audienceLabel("martians")).toBe("martians");
  });
});

describe("decidedFor names what was chosen on the user's behalf", () => {
  it("states audience, duration, emphasis, interactivity and size", () => {
    const facts = decidedFor(view());
    expect(facts).toHaveLength(5);
    expect(facts.every((f) => f.value.length > 0)).toBe(true);
    // The audit's complaint is that apply_defaults decides SILENTLY; every
    // one of these must be a readable value, never an enum token.
    expect(facts.find((f) => f.label === "Auditoriya")?.value).toBe("Bakalavr talabalari");
    expect(facts.find((f) => f.label === "Davomiylik")?.value).toBe("15 daqiqa");
    expect(facts.find((f) => f.label === "Slaydlar")?.value).toBe("11 ta");
  });

  it("says interactivity is absent rather than omitting the row", () => {
    const facts = decidedFor(view({ include_interactive: false }));
    expect(facts.find((f) => f.label === "Interaktiv")?.value).toBeTruthy();
  });
});

describe("swatches", () => {
  it("carries real hex values so the palette can be shown as colour", () => {
    const list = swatches(view());
    expect(list).toHaveLength(4);
    expect(list.every((s) => /^#[0-9A-Fa-f]{6}$/.test(s.hex))).toBe(true);
  });
});

describe("hasArgument", () => {
  it("is true for a planned deck", () => {
    expect(hasArgument(view())).toBe(true);
  });

  it("is false for a deck that predates the binding planner", () => {
    // DeckSpec.plan is optional; such a deck still has a design and a roster,
    // so the surface degrades instead of claiming an argument it never had.
    expect(hasArgument(view({ thesis: null, sections: [] }))).toBe(false);
  });
});
