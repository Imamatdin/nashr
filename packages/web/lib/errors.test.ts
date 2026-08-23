import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { creditCopy, describeError, fieldsOf, rateLimitCopy, reasonOf } from "./errors";

const soum = (n: number) => `${n} so'm`;

/** The shape lib/api.ts produces for a JSON `detail` object. */
function structured(status: number, detail: Record<string, unknown>): ApiError {
  return new ApiError(status, JSON.stringify(detail));
}

describe("no raw machine string ever reaches a rendered surface", () => {
  // The audit's §4 ledger: 22 sites printed things like
  // `Error: API 500: psycopg.errors.UndefinedColumn…` straight at the user.
  const machineStrings = [
    'psycopg.errors.UndefinedColumn: column "foo" does not exist',
    '[{"type":"too_short","loc":["body","sources"],"msg":"List should have at least 1 item"}]',
    "JSON object requested, multiple (or no) rows returned",
    "RuntimeError: image render failed",
  ];

  it.each(machineStrings)("keeps %s out of title and message", (raw) => {
    const friendly = describeError(new ApiError(500, raw));
    expect(friendly.title).not.toContain(raw);
    expect(friendly.message).not.toContain(raw);
    expect(friendly.title.length).toBeGreaterThan(0);
    expect(friendly.message.length).toBeGreaterThan(0);
    // The machine text survives, but only where a user has to opt in to it.
    expect(friendly.detail).toContain(raw);
  });

  it("still produces human copy for a reason code it has never seen", () => {
    const friendly = describeError(structured(500, { reason: "reactor_meltdown_42" }));
    expect(friendly.reason).toBe("reactor_meltdown_42");
    expect(friendly.message).not.toContain("reactor_meltdown_42");
    expect(friendly.action?.kind).toBe("retry");
  });

  it("never throws, whatever it is handed", () => {
    for (const value of [null, undefined, 42, { nope: true }, new Error("boom")]) {
      expect(() => describeError(value)).not.toThrow();
      expect(describeError(value).title.length).toBeGreaterThan(0);
    }
  });
});

describe("reasonOf", () => {
  it("reads a code out of a structured detail", () => {
    expect(reasonOf(structured(409, { reason: "brain_busy" }))).toBe("brain_busy");
  });

  it("accepts a bare-string detail as the code itself", () => {
    expect(reasonOf(new ApiError(404, "project_not_found"))).toBe("project_not_found");
  });

  it("refuses to treat prose as a code", () => {
    expect(reasonOf(new ApiError(500, "JSON object requested, multiple rows"))).toBeNull();
  });

  it("is null for anything that is not an ApiError", () => {
    expect(reasonOf(new TypeError("Failed to fetch"))).toBeNull();
  });
});

describe("network and timeout are not server faults", () => {
  it("blames the connection, not us, when fetch never reached the server", () => {
    const friendly = describeError(new TypeError("Failed to fetch"));
    expect(friendly.reason).toBe("network");
    expect(friendly.title).toContain("Internet");
  });

  it("names a timeout as a timeout", () => {
    const friendly = describeError(new DOMException("aborted", "AbortError"));
    expect(friendly.reason).toBe("timeout");
    expect(friendly.action?.kind).toBe("retry");
  });
});

describe("401 sends the user to a door", () => {
  it.each(["expired", "missing_bearer_token", "bad_signature"])("routes %s to login", (reason) => {
    expect(describeError(new ApiError(401, reason)).action?.kind).toBe("login");
  });

  it("routes an unrecognised 401 to login too", () => {
    expect(describeError(new ApiError(401, "who knows")).action?.kind).toBe("login");
  });
});

describe("creditCopy states the actual shortfall", () => {
  it("splices in balance, required and the gap", () => {
    const friendly = creditCopy(
      structured(402, { reason: "insufficient_balance", balance: 3_000, required: 10_000 }),
      soum,
    );
    expect(friendly.message).toContain("3000 so'm");
    expect(friendly.message).toContain("10000 so'm");
    expect(friendly.message).toContain("7000 so'm");
    // The dead end the audit found was a refusal with no way forward.
    expect(friendly.action?.kind).toBe("topup");
  });

  it("falls back to catalog copy when the body is not the expected shape", () => {
    const friendly = creditCopy(structured(402, { reason: "insufficient_balance" }), soum);
    expect(friendly.title).toBe("Kredit yetarli emas");
    expect(friendly.message).not.toContain("undefined");
    expect(friendly.message).not.toContain("NaN");
  });
});

describe("rateLimitCopy uses the 429 body instead of asserting 'tomorrow'", () => {
  it("says when the limit resets", () => {
    const resets = new Date(Date.now() + 20 * 60_000).toISOString();
    const friendly = rateLimitCopy(
      structured(429, { reason: "rate_limited", scope: "user", count: 11, limit: 10, resets_at: resets }),
    );
    expect(friendly.message).toContain("20 daqiqada");
    expect(friendly.message).toContain("10 ta");
    expect(friendly.message).not.toContain("ertaga");
  });

  it("names the per-IP case so a shared network is not read as the user's fault", () => {
    const friendly = rateLimitCopy(
      structured(429, { reason: "rate_limited", scope: "ip", count: 41, limit: 40, resets_at: new Date().toISOString() }),
    );
    expect(friendly.message).toContain("tarmoq");
  });

  it("degrades cleanly when the body carries no reset time", () => {
    const friendly = rateLimitCopy(structured(429, { reason: "rate_limited" }));
    expect(friendly.message).not.toContain("Invalid");
    expect(friendly.message).not.toContain("NaN");
  });
});

describe("fieldsOf", () => {
  it("hands back the structured fields for callers that branch on them", () => {
    expect(fieldsOf(structured(409, { reason: "fixes_exhausted", fix_limit: 2 })).fix_limit).toBe(2);
  });

  it("is an empty object for a bare-string detail", () => {
    expect(fieldsOf(new ApiError(404, "project_not_found"))).toEqual({});
  });
});

describe("designed states are not styled as failures", () => {
  it.each(["sources_not_ready", "brain_busy", "session_not_ready", "job_not_found"])(
    "%s reads as information, not an error",
    (reason) => {
      expect(describeError(structured(409, { reason })).tone).toBe("info");
    },
  );
});
