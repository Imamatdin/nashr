import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_RETURN_TO,
  consumeReturnTo,
  sanitizeReturnTo,
  stashReturnTo,
} from "./return-to";

const STORAGE_KEY = "nashr.returnTo";

function installLocalStorage(): Map<string, string> {
  const store = new Map<string, string>();
  const stub = {
    getItem: (key: string) => (store.has(key) ? (store.get(key) as string) : null),
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
  };
  Object.defineProperty(globalThis, "window", {
    value: { localStorage: stub },
    configurable: true,
    writable: true,
  });
  return store;
}

describe("sanitizeReturnTo", () => {
  it("accepts plain relative paths", () => {
    expect(sanitizeReturnTo("/new")).toBe("/new");
    expect(sanitizeReturnTo("/projects/abc-123")).toBe("/projects/abc-123");
  });

  it("preserves query strings verbatim", () => {
    expect(sanitizeReturnTo("/new?lang=kaa")).toBe("/new?lang=kaa");
  });

  it("accepts an absolute URL inside the query — only the path segment steers navigation", () => {
    expect(sanitizeReturnTo("/callback?next=https://evil.com")).toBe(
      "/callback?next=https://evil.com",
    );
  });

  it.each([
    ["https://evil.com"],
    ["http://evil.com"],
    ["//evil.com"],
    ["/\\evil.com"],
    ["javascript:alert(1)"],
    ["/new\u0000x"],
    ["/new x"],
    [""],
  ])("rejects %j", (raw) => {
    expect(sanitizeReturnTo(raw)).toBe(DEFAULT_RETURN_TO);
  });

  it("rejects null and undefined", () => {
    expect(sanitizeReturnTo(null)).toBe(DEFAULT_RETURN_TO);
    expect(sanitizeReturnTo(undefined)).toBe(DEFAULT_RETURN_TO);
  });

  it("rejects an over-long path", () => {
    expect(sanitizeReturnTo("/" + "a".repeat(599))).toBe(DEFAULT_RETURN_TO);
  });
});

describe("stashReturnTo / consumeReturnTo", () => {
  let store: Map<string, string>;

  beforeEach(() => {
    store = installLocalStorage();
  });

  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(globalThis, "window");
  });

  it("round-trips a safe path", () => {
    stashReturnTo("/new?lang=kaa");
    expect(consumeReturnTo()).toBe("/new?lang=kaa");
  });

  it("sanitizes on write", () => {
    stashReturnTo("https://evil.com");
    expect(consumeReturnTo()).toBe(DEFAULT_RETURN_TO);
  });

  it("clears the key so a second consume returns the default", () => {
    stashReturnTo("/new");
    expect(consumeReturnTo()).toBe("/new");
    expect(store.has(STORAGE_KEY)).toBe(false);
    expect(consumeReturnTo()).toBe(DEFAULT_RETURN_TO);
  });

  it("returns the default once the stash has expired", () => {
    vi.useFakeTimers();
    stashReturnTo("/new");
    vi.advanceTimersByTime(61 * 60 * 1000);
    expect(consumeReturnTo()).toBe(DEFAULT_RETURN_TO);
  });

  it("returns the default on corrupted JSON", () => {
    store.set(STORAGE_KEY, "{not json");
    expect(consumeReturnTo()).toBe(DEFAULT_RETURN_TO);
    expect(store.has(STORAGE_KEY)).toBe(false);
  });

  it("re-sanitizes the stored value", () => {
    store.set(STORAGE_KEY, JSON.stringify({ path: "//evil.com", exp: Date.now() + 60_000 }));
    expect(consumeReturnTo()).toBe(DEFAULT_RETURN_TO);
  });

  it("returns the default when there is no window", () => {
    Reflect.deleteProperty(globalThis, "window");
    expect(consumeReturnTo()).toBe(DEFAULT_RETURN_TO);
    expect(() => stashReturnTo("/new")).not.toThrow();
  });
});
