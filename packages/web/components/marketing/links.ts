// The marketing sitemap in one place: what the header and footer link to, and
// how a marketing CTA hands a visitor to the app. Nothing here imports app
// modules — the marketing tree stays a leaf of the build.

export const ROUTES = {
  home: "/",
  presentations: "/taqdimot",
  articles: "/maqola",
  pricing: "/narxlar",
  teachers: "/oqituvchilar",
  about: "/haqida",
  help: "/yordam",
  privacy: "/maxfiylik",
  terms: "/shartlar",
} as const;

export const APP = {
  login: "/login",
  create: "/new",
} as const;

// TODO(FOUNDER): confirm the real handles before merge — these are placeholders
// and must not ship pointing at accounts we do not own.
export const SOCIAL = {
  telegram: "https://t.me/nashr_uz",
  instagram: "https://instagram.com/nashr.uz",
} as const;

export const NAV: ReadonlyArray<{ href: string; label: string }> = [
  { href: ROUTES.presentations, label: "Taqdimot" },
  { href: ROUTES.articles, label: "Maqola" },
  { href: ROUTES.pricing, label: "Narxlar" },
  { href: ROUTES.teachers, label: "O‘qituvchilarga" },
];

// sanitizeReturnTo (lib/return-to.ts) drops anything over 512 characters to
// /projects, which would lose both the topic and the destination. A topic long
// enough to threaten that cap is a paragraph, not a topic.
const MAX_TOPIC = 200;

/** Where every marketing CTA points: the door, carrying /new as its return. */
export function startHref(topic?: string): string {
  const trimmed = topic?.trim();
  if (!trimmed) return `${APP.login}?returnTo=${encodeURIComponent(APP.create)}`;
  const target = `${APP.create}?topic=${encodeURIComponent(trimmed.slice(0, MAX_TOPIC))}`;
  return `${APP.login}?returnTo=${encodeURIComponent(target)}`;
}
