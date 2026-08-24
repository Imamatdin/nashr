import { describe, expect, it } from "vitest";
import type { InterviewQuestionView, InterviewView, PricingEntryView } from "./api";
import {
  CHARGE_NOTE,
  DECIDE_FOR_ME,
  FORCED_FORMATS,
  buildAnswers,
  decisionSummary,
  planRows,
  prepareQuestions,
  submitBlock,
} from "./creation";

function question(over: Partial<InterviewQuestionView>): InterviewQuestionView {
  return {
    question_id: "audience",
    question_text: "Kim uchun?",
    question_type: "single_select",
    options: null,
    min_value: null,
    max_value: null,
    default_value: null,
    placeholder: null,
    help_text: null,
    ...over,
  };
}

function view(over: Partial<InterviewView> = {}): InterviewView {
  return {
    questions: [],
    detected_domain: "environmental",
    estimated_slide_count: 12,
    available_stats_count: 4,
    available_people_count: 2,
    ...over,
  };
}

const SELECT = question({
  question_id: "audience",
  options: [
    { value: "undergraduate", label: "Talaba", is_default: true },
    { value: "academic", label: "Akademik", is_default: false },
    { value: DECIDE_FOR_ME, label: "O‘zingiz tanlang", is_default: false },
  ],
});

const MULTI = question({
  question_id: "emphasis",
  question_type: "multi_select",
  question_text: "Nimaga urg‘u?",
  options: [
    { value: "data_driven", label: "Raqamlar", is_default: false },
    { value: "narrative", label: "Hikoya", is_default: false },
  ],
});

const SLIDER = question({
  question_id: "duration",
  question_type: "slider",
  question_text: "Necha daqiqa?",
  min_value: 5,
  max_value: 45,
  default_value: 15,
});

const TEXT = question({
  question_id: "closing_ask",
  question_type: "text",
  question_text: "Yakuniy chaqiriq?",
  help_text: "ixtiyoriy",
});

describe("prepareQuestions maps the wire onto the approval card", () => {
  it("keeps option LABELS on the card but remembers the engine's values", () => {
    const [prepared] = prepareQuestions(view({ questions: [SELECT] }));
    expect(prepared.card.type).toBe("radio");
    expect(prepared.card.options.map((o) => o.label)).toEqual([
      "Talaba",
      "Akademik",
      "O‘zingiz tanlang",
    ]);
    expect(prepared.valueByLabel["Talaba"]).toBe("undergraduate");
    expect(prepared.card.options[0].hint).toBe("standart");
  });

  it("renders a multi_select as a checkbox question", () => {
    const [prepared] = prepareQuestions(view({ questions: [MULTI] }));
    expect(prepared.kind).toBe("multi");
    expect(prepared.card.type).toBe("check");
  });

  it("turns the slider into discrete minute options inside its own range", () => {
    const [prepared] = prepareQuestions(view({ questions: [SLIDER] }));
    expect(prepared.card.options.map((o) => o.label)).toEqual([
      "10 daqiqa",
      "15 daqiqa",
      "20 daqiqa",
      "30 daqiqa",
      "45 daqiqa",
    ]);
    expect(prepared.card.options[1].hint).toBe("tavsiya etilgan");
  });

  it("clamps slider stops to a narrow range instead of offering impossible ones", () => {
    const [prepared] = prepareQuestions(
      view({ questions: [question({ ...SLIDER, min_value: 12, max_value: 20 })] }),
    );
    expect(prepared.card.options.map((o) => o.label)).toEqual(["15 daqiqa", "20 daqiqa"]);
  });

  it("gives a free-text question a skip option, since a card with no options cannot advance", () => {
    const [prepared] = prepareQuestions(view({ questions: [TEXT] }));
    expect(prepared.kind).toBe("text");
    expect(prepared.card.options).toHaveLength(1);
    expect(prepared.card.q).toContain("ixtiyoriy");
  });
});

describe("buildAnswers speaks values, not labels", () => {
  const prepared = prepareQuestions(view({ questions: [SELECT, MULTI, SLIDER, TEXT] }));

  it("keys by question_id and sends the option value", () => {
    const payload = buildAnswers(prepared, [
      { question: "Kim uchun?", selected: ["Akademik"] },
      { question: "Nimaga urg‘u?", selected: ["Raqamlar", "Hikoya"] },
      { question: "Necha daqiqa?", selected: ["30 daqiqa"] },
      { question: "Yakuniy chaqiriq?", selected: [], custom: "  Suv tejashga o‘ting  " },
    ]);
    expect(payload).toEqual({
      audience: "academic",
      emphasis: ["data_driven", "narrative"],
      duration: 30,
      closing_ask: "Suv tejashga o‘ting",
    });
  });

  it("omits a question the user skipped rather than sending a sentinel", () => {
    const payload = buildAnswers(prepared, [
      { question: "Kim uchun?", selected: [] },
      { question: "Nimaga urg‘u?", selected: [] },
      { question: "Necha daqiqa?", selected: [] },
      { question: "Yakuniy chaqiriq?", selected: ["O‘tkazib yuborish"] },
    ]);
    expect(payload).toEqual({});
  });

  it("drops free text typed against a select question instead of sending an enum miss", () => {
    // The card's custom field is card-wide; a sentence here would match no
    // AudienceType server-side, so the engine's own default is the honest result.
    const payload = buildAnswers(prepared, [
      { question: "Kim uchun?", selected: [], custom: "vazirlik xodimlari" },
      { question: "Nimaga urg‘u?", selected: [] },
      { question: "Necha daqiqa?", selected: [] },
      { question: "Yakuniy chaqiriq?", selected: [] },
    ]);
    expect(payload).toEqual({});
  });

  it("survives a short answer array without inventing keys", () => {
    expect(buildAnswers(prepared, [])).toEqual({});
  });

  it("passes decide_for_me straight through — the engine knows that sentinel", () => {
    const payload = buildAnswers(prepared, [
      { question: "Kim uchun?", selected: ["O‘zingiz tanlang"] },
    ]);
    expect(payload).toEqual({ audience: DECIDE_FOR_ME });
  });
});

describe("decisionSummary says what was decided", () => {
  it("names the domain, the size and the evidence the deck will lean on", () => {
    const summary = decisionSummary(view());
    expect(summary.kind).toBe("from_sources");
    expect(summary.lines.join(" ")).toContain("ekologiya");
    expect(summary.lines.join(" ")).toContain("12 ta slayd");
    expect(summary.lines.join(" ")).toContain("4 ta raqamli dalil");
    expect(summary.lines.join(" ")).toContain("2 ta shaxs");
  });

  it("does not claim numeric evidence that is not there", () => {
    const summary = decisionSummary(view({ available_stats_count: 0, available_people_count: 0 }));
    const text = summary.lines.join(" ");
    expect(text).toContain("raqamli dalil topilmadi");
    expect(text).not.toContain("shaxs eslatilgan");
  });

  it("still produces honest copy on the sources_not_ready path, with no error voice", () => {
    // 409 on a first run is DESIGNED: sources are processed during generation.
    const summary = decisionSummary(null);
    expect(summary.kind).toBe("sources_not_ready");
    expect(summary.lines.length).toBeGreaterThan(0);
    const text = `${summary.lead} ${summary.lines.join(" ")}`;
    expect(text.toLowerCase()).toContain("keyingi generatsiyada");
    expect(text.toLowerCase()).not.toContain("xato");
  });

  it("falls back to the raw domain code rather than rendering nothing", () => {
    expect(decisionSummary(view({ detected_domain: "astrophysics" })).lines[0]).toContain(
      "astrophysics",
    );
  });
});

describe("planRows says what will happen, not just the price", () => {
  const pricing: PricingEntryView = {
    package: "presentation_standard",
    price: 10000,
    ai_images: 2,
    fix_allowance: 3,
  };
  const base = {
    topic: "Orol dengizi",
    languageLabel: "O‘zbekcha",
    packageLabel: "Standart",
    sourceCount: 3,
    fallbackPrice: 99999,
    balance: 25000,
    estimatedSlides: 12,
    soum: (n: number) => `${n} so‘m`,
  };

  function valueOf(rows: ReturnType<typeof planRows>, label: string): string | undefined {
    return rows.find((row) => row.label === label)?.value;
  }

  it("prefers the server price over the client's list price", () => {
    const rows = planRows({ ...base, pricing });
    expect(valueOf(rows, "Narx")).toBe("10000 so‘m");
    expect(valueOf(rows, "Keyin qoladi")).toBe("15000 so‘m");
  });

  it("falls back to the list price only when /pricing has not answered", () => {
    const rows = planRows({ ...base, pricing: null });
    expect(valueOf(rows, "Narx")).toBe("99999 so‘m");
    expect(valueOf(rows, "AI rasm")).toBe("paket bo‘yicha");
    expect(rows.some((row) => row.label === "Tahrirlar")).toBe(false);
  });

  it("states the image budget and the fix allowance from the server", () => {
    const rows = planRows({ ...base, pricing });
    expect(valueOf(rows, "AI rasm")).toBe("2 tagacha");
    expect(valueOf(rows, "Tahrirlar")).toBe("3 ta bepul tuzatish");
  });

  it("says a zero-image tier is typographic instead of showing a bare 0", () => {
    const rows = planRows({ ...base, pricing: { ...pricing, ai_images: 0, fix_allowance: 0 } });
    expect(valueOf(rows, "AI rasm")).toBe("yo‘q — tipografik dizayn");
    expect(valueOf(rows, "Tahrirlar")).toBe("yo‘q");
  });

  it("always names all three forced formats", () => {
    expect(valueOf(planRows({ ...base, pricing }), "Formatlar")).toBe(FORCED_FORMATS);
  });

  it("omits the slide estimate when the interview never gave one", () => {
    const rows = planRows({ ...base, pricing, estimatedSlides: null });
    expect(rows.some((row) => row.label === "Slaydlar")).toBe(false);
  });

  it("omits the post-charge balance rather than guessing it", () => {
    const rows = planRows({ ...base, pricing, balance: null });
    expect(rows.some((row) => row.label === "Keyin qoladi")).toBe(false);
  });

  it("never shows a negative remainder when the balance is short", () => {
    const rows = planRows({ ...base, pricing, balance: 2000 });
    expect(valueOf(rows, "Keyin qoladi")).toBe("0 so‘m");
  });

  it("promises the refund in the same breath as the charge", () => {
    expect(CHARGE_NOTE).toContain("qaytariladi");
  });
});

describe("submitBlock — one rule for hint, disabled state and guard (G9)", () => {
  const ok = { hasTopic: true, uploading: false, readyCount: 2, failedCount: 0 };

  it("lets a topic with at least one registered source through", () => {
    expect(submitBlock(ok)).toBeNull();
  });

  it("blocks a sourceless run client-side — the API requires at least one", () => {
    expect(submitBlock({ ...ok, readyCount: 0 })).toContain("Kamida bitta manba");
  });

  it("points at the per-row retry when every upload failed", () => {
    expect(submitBlock({ ...ok, readyCount: 0, failedCount: 2 })).toContain("qayta urinish");
  });

  it("waits for uploads in flight", () => {
    expect(submitBlock({ ...ok, uploading: true })).toContain("yuklanmoqda");
  });

  it("asks for the topic first", () => {
    expect(submitBlock({ ...ok, hasTopic: false })).toContain("mavzuni");
  });
});
