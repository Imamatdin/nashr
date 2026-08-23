// The tier table the marketing site quotes.
//
// TODO(W): replace with GET /pricing — packages/api/routes/credits.py already
// serves the canonical table (price, ai_images, fix_allowance) from
// CreditLedger.PRICING, and the marketing pages should read it rather than
// carry a copy. Until the web has a fetch path for it, every number below is
// copied, not invented:
//   - id / name / price / desc  ..... verbatim from packages/web/lib/packages.ts
//   - price (server truth) .......... packages/platform/credits.py PRICING
//   - aiImages ...................... packages/core/constants.py
//                                     PRESENTATION_TIER_IMAGE_LIMITS
//   - fixes ......................... packages/bot/sessions/budget.py
//                                     SESSION_FIX_LIMITS (flagged PLACEHOLDER
//                                     economics there — a Stage 5 decision)
// The marketing tree deliberately does not import lib/packages.ts: the site
// must not start pulling app modules across the boundary.

export interface MarketingTier {
  id: "presentation_basic" | "presentation_standard" | "presentation_premium";
  name: string;
  price: number;
  desc: string;
  aiImages: number;
  fixes: number;
  featured?: boolean;
  /** What the tier includes, in the reader language. */
  includes: ReadonlyArray<string>;
}

export const TIERS: ReadonlyArray<MarketingTier> = [
  {
    id: "presentation_basic",
    name: "Oddiy",
    price: 5000,
    desc: "AI rasmsiz, toza tipografik dizayn",
    aiImages: 0,
    fixes: 1,
    includes: [
      "Manbaga bog‘langan slaydlar",
      "HTML, PDF va PPTX",
      "AI rasm yo‘q: tipografiya, gradient va geometrik naqsh",
      "1 ta tahrir",
    ],
  },
  {
    id: "presentation_standard",
    name: "Standart",
    price: 10000,
    desc: "Muqova + asosiy vizual (2 AI rasm)",
    aiImages: 2,
    fixes: 2,
    featured: true,
    includes: [
      "Manbaga bog‘langan slaydlar",
      "HTML, PDF va PPTX",
      "2 ta AI rasm: muqova va bitta asosiy vizual",
      "2 ta tahrir",
    ],
  },
  {
    id: "presentation_premium",
    name: "Premium",
    price: 15000,
    desc: "5 tagacha AI rasm",
    aiImages: 5,
    fixes: 3,
    includes: [
      "Manbaga bog‘langan slaydlar",
      "HTML, PDF va PPTX",
      "5 tagacha AI rasm, butun taqdimot bo‘ylab bitta uslub",
      "3 ta tahrir",
    ],
  },
];

// Free-credit economics, for the pricing FAQ. Source: packages/platform/
// credits.py — FREE_CREDIT_VALUE / FREE_DAILY_CAP / FREE_WEEKLY_CAP /
// FREE_PROJECT_CAP. Same TODO(W): these belong to GET /pricing too.
export const FREE_CREDIT = {
  value: 5000,
  dailyCap: 3,
  weeklyCap: 10,
  projectCap: 5,
} as const;

/** Verbatim from lib/packages.ts so the marketing tree stays self-contained. */
export function soum(amount: number): string {
  return `${amount.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ")} so‘m`;
}
