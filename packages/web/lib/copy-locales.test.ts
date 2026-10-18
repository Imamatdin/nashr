import { describe, expect, it } from "vitest";
import { ARTICLE_COPY } from "../components/article-workspace-copy";
import { EVIDENCE_COPY } from "../components/evidence-library-copy";
import { HOME_COPY } from "../components/home-copy";
import { NEW_PROJECT_COPY } from "../components/new-project-copy";
import { DESIGNER_COPY } from "../components/presentation-designer-copy";
import { PROJECTS_COPY } from "../components/projects-copy";
import { WORKSPACE_COPY } from "../components/workspace-copy";
import { LOCALES } from "./locale";

// D9: uz, ru, kaa and en are equal; every user-facing string exists in all
// four. A locale added to LOCALES must be present in every copy object with the
// same key set, or one language silently falls back to another. The type system
// enforces this for the Record<Locale> copies, but DESIGNER_COPY derives its type
// from its own `en` block, so a missing or misshapen kaa block there is a type
// no-op; this test is the guard that catches it for every exported copy object.

type AnyRecord = Record<string, unknown>;

/**
 * A structural fingerprint of an object's nested key names, ignoring leaf
 * values. Arrays, functions, strings and numbers are leaves; plain objects
 * recurse. Two locale blocks with the same fingerprint expose the same keys.
 */
function keyShape(value: unknown): unknown {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const obj = value as AnyRecord;
    const out: AnyRecord = {};
    for (const key of Object.keys(obj).sort()) out[key] = keyShape(obj[key]);
    return out;
  }
  return null;
}

const COPIES: Record<string, AnyRecord> = {
  ARTICLE_COPY,
  EVIDENCE_COPY,
  HOME_COPY,
  NEW_PROJECT_COPY,
  DESIGNER_COPY,
  PROJECTS_COPY,
  WORKSPACE_COPY,
};

const EXPECTED = [...LOCALES].sort();

describe("copy objects cover every locale with identical key sets", () => {
  for (const [name, copy] of Object.entries(COPIES)) {
    it(`${name} has exactly ${EXPECTED.join(", ")}`, () => {
      expect(Object.keys(copy).sort()).toEqual(EXPECTED);
    });

    it(`${name} exposes the same keys in every locale`, () => {
      const reference = keyShape(copy[LOCALES[0]]);
      for (const code of LOCALES) {
        expect(keyShape(copy[code]), `${name}.${code}`).toEqual(reference);
      }
    });
  }
});
