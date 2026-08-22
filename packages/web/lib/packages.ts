// The purchasable tiers and the four output languages. Prices are server
// truth; the copy here only has to match what the API charges.

export const PACKAGES = [
  {
    id: "presentation_basic",
    name: "Oddiy",
    price: 5000,
    desc: "AI rasmsiz — toza tipografik dizayn",
  },
  {
    id: "presentation_standard",
    name: "Standart",
    price: 10000,
    desc: "Muqova + asosiy vizual (2 AI rasm)",
  },
  {
    id: "presentation_premium",
    name: "Premium",
    price: 15000,
    desc: "5 tagacha AI rasm",
  },
] as const;

export type PackageId = (typeof PACKAGES)[number]["id"];
export type PackageEntry = (typeof PACKAGES)[number];

export const DEFAULT_PACKAGE: PackageId = "presentation_standard";

export const LANGUAGES = [
  { code: "uz", name: "O‘zbekcha" },
  { code: "kaa", name: "Qaraqalpaqsha" },
  { code: "ru", name: "Русский" },
  { code: "en", name: "English" },
] as const;

export type LanguageCode = (typeof LANGUAGES)[number]["code"];

export const DEFAULT_LANGUAGE: LanguageCode = "uz";

export function soum(amount: number): string {
  return `${amount.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ")} so‘m`;
}

export function packageOf(id: PackageId): PackageEntry {
  return PACKAGES.find((entry) => entry.id === id) ?? PACKAGES[1];
}

export function isLanguageCode(value: string): value is LanguageCode {
  return LANGUAGES.some((entry) => entry.code === value);
}

export function languageName(code: LanguageCode): string {
  return LANGUAGES.find((entry) => entry.code === code)?.name ?? code;
}

// Migration 010 may be unapplied in prod, so package_tier arrives as
// string | null | undefined; the server bills a missing tier as the standard
// package (_LEGACY_PACKAGE), and the UI has to say the same thing.
export function tierOf(tier: string | null | undefined): PackageEntry {
  if (typeof tier === "string" && PACKAGES.some((entry) => entry.id === tier)) {
    return packageOf(tier as PackageId);
  }
  return packageOf(DEFAULT_PACKAGE);
}
