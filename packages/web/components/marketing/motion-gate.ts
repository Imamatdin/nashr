// The five conditions any canvas on this site has to clear before its module is
// even fetched. Shared by the hero ring and the /maqola desk plate so the two
// answers can never drift apart.

const MIN_WIDTH = 768;

interface SaveDataConnection {
  saveData?: boolean;
}

export function motionEligible(needsWebgl = false): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  if (window.innerWidth < MIN_WIDTH) return false;
  const connection = (navigator as Navigator & { connection?: SaveDataConnection }).connection;
  if (connection?.saveData) return false;

  const probe = document.createElement("canvas");
  if (typeof probe.getContext !== "function") return false;
  if (!needsWebgl) return Boolean(probe.getContext("2d"));
  try {
    return Boolean(probe.getContext("webgl2") ?? probe.getContext("webgl"));
  } catch {
    return false;
  }
}

/**
 * Runs after the page has finished loading and the browser goes idle, so a
 * decorative canvas never competes with the LCP paint. Returns its own cancel.
 */
export function afterLoadWhenIdle(run: () => void): () => void {
  let cancelled = false;
  let idle = 0;
  const idleSupported = typeof window.requestIdleCallback === "function";

  function schedule(): void {
    if (cancelled) return;
    idle = idleSupported
      ? window.requestIdleCallback(run, { timeout: 2500 })
      : window.setTimeout(run, 800);
  }

  if (document.readyState === "complete") schedule();
  else window.addEventListener("load", schedule, { once: true });

  return () => {
    cancelled = true;
    window.removeEventListener("load", schedule);
    if (idleSupported) window.cancelIdleCallback(idle);
    else window.clearTimeout(idle);
  };
}
