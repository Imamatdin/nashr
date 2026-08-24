import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import {
  LINK_LIFETIME_CAPTION,
  classifyShareFailure,
  downloadFreshnessNote,
  signedUrlLifetime,
} from "./share-link";

describe("classifyShareFailure", () => {
  it("reads a missing or disabled link as final, with no retry", () => {
    const failure = classifyShareFailure(new ApiError(404, "not_found"));
    expect(failure.retryable).toBe(false);
    expect(failure.title).toBe("Havola ishlamaydi");
    expect(failure.message).toContain("o‘chirgan");
  });

  it("reads a rotated link differently from a missing one, and never retries it", () => {
    const gone = classifyShareFailure(new ApiError(410, "gone"));
    const missing = classifyShareFailure(new ApiError(404, "not_found"));
    expect(gone.retryable).toBe(false);
    expect(gone.title).not.toBe(missing.title);
    expect(gone.message).not.toBe(missing.message);
  });

  it("offers retry on a server fault", () => {
    const failure = classifyShareFailure(new ApiError(500, "boom"));
    expect(failure.retryable).toBe(true);
    expect(failure.title).not.toBe("Havola ishlamaydi");
  });

  it("offers retry when the request timed out", () => {
    const failure = classifyShareFailure(new DOMException("aborted", "AbortError"));
    expect(failure.retryable).toBe(true);
    expect(failure.reason).toBe("timeout");
  });

  it("names the network, not the server, when the fetch never landed", () => {
    const failure = classifyShareFailure(new TypeError("Failed to fetch"));
    expect(failure.retryable).toBe(true);
    expect(failure.reason).toBe("network");
  });

  it("keeps the rate-limit numbers and stays retryable", () => {
    const failure = classifyShareFailure(
      new ApiError(429, JSON.stringify({ reason: "rate_limited", limit: 30, scope: "ip" })),
    );
    expect(failure.retryable).toBe(true);
    expect(failure.message).toContain("30");
  });

  it("never leaks the machine string into rendered copy", () => {
    const failure = classifyShareFailure(new ApiError(500, "psycopg.errors.UndefinedColumn"));
    expect(failure.title).not.toContain("psycopg");
    expect(failure.message).not.toContain("psycopg");
    expect(failure.detail).toContain("psycopg");
  });
});

describe("signedUrlLifetime", () => {
  it("reports minutes for the html TTL", () => {
    expect(signedUrlLifetime(900)).toBe("15 daqiqa");
  });

  it("reports hours for the download TTL", () => {
    expect(signedUrlLifetime(3600)).toBe("1 soat");
  });

  it("refuses nonsense instead of inventing a duration", () => {
    expect(signedUrlLifetime(0)).toBeNull();
    expect(signedUrlLifetime(-5)).toBeNull();
    expect(signedUrlLifetime(Number.NaN)).toBeNull();
  });
});

describe("expiry copy", () => {
  it("never states a day count for a signed-URL TTL", () => {
    for (const seconds of [900, 3600, 0, 86_400]) {
      expect(downloadFreshnessNote(seconds)).not.toMatch(/kun/i);
    }
    expect(LINK_LIFETIME_CAPTION).not.toMatch(/kun/i);
  });

  it("ties the note to the lifetime it was handed", () => {
    expect(downloadFreshnessNote(3600)).toContain("1 soat");
    expect(downloadFreshnessNote(900)).toContain("15 daqiqa");
  });
});
