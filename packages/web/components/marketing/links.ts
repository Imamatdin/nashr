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
// /projects — losing the topic AND the destination, which is worse than never
// carrying the topic at all. The cap applies to the DECODED return path, and
// encodeURIComponent turns one Cyrillic letter into six characters, so a
// Russian or Karakalpak topic reaches it at about eighty letters. Both limits
// are enforced below, the second against the encoded length.
const MAX_TOPIC = 200;
const MAX_RETURN_PATH = 480;

const doorHref = (returnTo: string): string =>
  `${APP.login}?returnTo=${encodeURIComponent(returnTo)}`;

const targetFor = (topic: string): string =>
  `${APP.create}?topic=${encodeURIComponent(topic)}`;

/** Where every marketing CTA points: the door, carrying /new as its return. */
export function startHref(topic?: string): string {
  const trimmed = topic?.trim();
  if (!trimmed) return doorHref(APP.create);

  // Truncate the topic, never the encoded string: slicing that would cut a
  // %XX escape in half and the sanitizer would reject the whole path.
  let value = trimmed.slice(0, MAX_TOPIC);
  while (value.length > 0 && targetFor(value).length > MAX_RETURN_PATH) {
    value = value.slice(0, -1);
  }
  if (!value) return doorHref(APP.create);
  return doorHref(targetFor(value));
}
