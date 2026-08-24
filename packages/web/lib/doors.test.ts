import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import {
  BRIDGE_DEADLINE_MS,
  CALLBACK_DEADLINE_MS,
  RESEND_COOLDOWN_MS,
  decideDoor,
  describeDoorFailure,
  hasMiniAppMarker,
  localDoorFailure,
  loginHref,
  resendState,
} from "./doors";

const MACHINE = /[a-z]+_[a-z_]+|HTTP \d{3}|supabase|exchange failed/;

describe("resendState", () => {
  it("allows the first send", () => {
    expect(resendState(null, 1_000)).toEqual({ canResend: true, secondsLeft: 0 });
  });

  it("blocks a resend during the cooldown and counts down", () => {
    const sentAt = 100_000;
    expect(resendState(sentAt, sentAt)).toEqual({
      canResend: false,
      secondsLeft: RESEND_COOLDOWN_MS / 1000,
    });
    expect(resendState(sentAt, sentAt + 30_000)).toEqual({ canResend: false, secondsLeft: 30 });
    expect(resendState(sentAt, sentAt + 59_100).secondsLeft).toBe(1);
  });

  it("re-opens exactly at the cooldown boundary", () => {
    const sentAt = 100_000;
    expect(resendState(sentAt, sentAt + RESEND_COOLDOWN_MS)).toEqual({
      canResend: true,
      secondsLeft: 0,
    });
    expect(resendState(sentAt, sentAt + RESEND_COOLDOWN_MS + 5_000).canResend).toBe(true);
  });
});

describe("decideDoor", () => {
  it("proves the Telegram identity when only initData is present", () => {
    expect(decideDoor("query_id=A&hash=b", false)).toBe("telegram");
  });

  it("offers the link when a signed-in user is inside Telegram", () => {
    expect(decideDoor("query_id=A&hash=b", true)).toBe("link");
  });

  it("forwards a visitor who already holds a session", () => {
    expect(decideDoor(null, true)).toBe("forward");
  });

  it("shows the doors to everyone else", () => {
    expect(decideDoor(null, false)).toBe("offer");
    expect(decideDoor("", false)).toBe("offer");
  });
});

describe("hasMiniAppMarker", () => {
  it("recognises the Mini App fragment", () => {
    expect(hasMiniAppMarker("#tgWebAppData=query_id%3DA&tgWebAppVersion=7.0")).toBe(true);
  });

  it("is false for an ordinary browser URL", () => {
    expect(hasMiniAppMarker("")).toBe(false);
    expect(hasMiniAppMarker("#access_token=abc")).toBe(false);
  });
});

describe("loginHref", () => {
  it("carries the place the user was going", () => {
    expect(loginHref("/projects/9?job=1")).toBe("/login?returnTo=%2Fprojects%2F9%3Fjob%3D1");
  });

  it("stays bare for the default destination", () => {
    expect(loginHref("/projects")).toBe("/login");
  });

  it("refuses an off-origin destination", () => {
    expect(loginHref("//evil.example")).toBe("/login");
    expect(loginHref("https://evil.example/x")).toBe("/login");
  });
});

describe("failure classification", () => {
  it("maps a known auth reason to human copy, machine text collapsed", () => {
    const friendly = describeDoorFailure(new ApiError(503, "telegram_auth_backend_down"));
    expect(friendly.title).toBe("Kirish vaqtincha ishlamayapti");
    expect(friendly.message).not.toMatch(MACHINE);
    expect(friendly.reason).toBe("telegram_auth_backend_down");
    expect(friendly.detail).toContain("telegram_auth_backend_down");
  });

  it("maps an expired Telegram proof", () => {
    const friendly = describeDoorFailure(new ApiError(401, "initdata_expired"));
    expect(friendly.title).toBe("Telegram havolasi eskirdi");
    expect(friendly.message).not.toMatch(MACHINE);
  });

  it("still gives human copy for an unknown reason", () => {
    const friendly = describeDoorFailure(new ApiError(500, "exchange failed: upstream 500"));
    expect(friendly.title).not.toMatch(MACHINE);
    expect(friendly.message).not.toMatch(MACHINE);
    expect(friendly.detail).toContain("exchange failed: upstream 500");
  });

  it("names a GoTrue AuthError without printing its English prose", () => {
    const authError = new Error("Email rate limit exceeded");
    authError.name = "AuthApiError";
    const friendly = describeDoorFailure(authError, "otp_send_failed");
    expect(friendly.title).toBe("Havola yuborilmadi");
    expect(friendly.message).not.toContain("rate limit");
    expect(friendly.detail).toContain("Email rate limit exceeded");
  });

  it("keeps the offline copy for a fetch that never left", () => {
    const friendly = describeDoorFailure(new TypeError("Failed to fetch"), "oauth_start_failed");
    expect(friendly.reason).toBe("network");
  });

  it("describes the local callback failures without internal vocabulary", () => {
    const noSession = localDoorFailure("no_supabase_session", "supabase sessiya topilmadi");
    expect(noSession.title).not.toMatch(MACHINE);
    expect(noSession.message).not.toMatch(MACHINE);
    expect(noSession.detail).toBe("supabase sessiya topilmadi");
    expect(noSession.action?.kind).toBe("login");

    expect(localDoorFailure("timeout").action?.kind).toBe("login");
    expect(localDoorFailure("cancelled").title).toBe("Kirish bekor qilindi");
  });
});

describe("deadlines", () => {
  it("waits longer than the api request abort, and less for the bridge", () => {
    expect(CALLBACK_DEADLINE_MS).toBeGreaterThan(20_000);
    expect(BRIDGE_DEADLINE_MS).toBeLessThan(CALLBACK_DEADLINE_MS);
  });
});
