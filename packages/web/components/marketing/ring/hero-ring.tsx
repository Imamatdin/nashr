"use client";

// The gate in front of the ring. The poster is the hero image and ships in the
// server HTML; the canvas is an upgrade that only downloads when every one of
// the budget's conditions holds — the viewport intersects, motion is welcome,
// the visitor is not on Save-Data, the screen is wide enough, and a 2D context
// exists at all. Anything short of that and the poster is the whole hero, with
// no ring module fetched.

import Image from "next/image";
import { useEffect, useRef, useState, type ComponentType } from "react";
import type { RingCanvasProps } from "./ring-canvas";

const MIN_WIDTH = 768;

interface SaveDataConnection {
  saveData?: boolean;
}

function eligible(): boolean {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  if (window.innerWidth < MIN_WIDTH) return false;
  const connection = (navigator as Navigator & { connection?: SaveDataConnection }).connection;
  if (connection?.saveData) return false;
  const probe = document.createElement("canvas");
  return typeof probe.getContext === "function" && Boolean(probe.getContext("2d"));
}

export function HeroRing({
  tiles,
  poster,
  label,
}: {
  tiles: ReadonlyArray<string>;
  poster: string;
  label: string;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [Ring, setRing] = useState<ComponentType<RingCanvasProps> | null>(null);
  const [swapped, setSwapped] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !eligible()) return;

    let cancelled = false;
    let idle = 0;

    function load(): void {
      void import("./ring-canvas").then((module) => {
        if (!cancelled) setRing(() => module.default);
      });
    }

    // After the page has finished loading, and then only when the browser is
    // idle: the ring must never compete with the LCP paint for bandwidth.
    const idleSupported = typeof window.requestIdleCallback === "function";

    function schedule(): void {
      if (cancelled) return;
      idle = idleSupported
        ? window.requestIdleCallback(load, { timeout: 2500 })
        : window.setTimeout(load, 800);
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        if (document.readyState === "complete") schedule();
        else window.addEventListener("load", schedule, { once: true });
      },
      { rootMargin: "200px" },
    );
    observer.observe(host);

    return () => {
      cancelled = true;
      observer.disconnect();
      window.removeEventListener("load", schedule);
      if (idleSupported) window.cancelIdleCallback(idle);
      else window.clearTimeout(idle);
    };
  }, []);

  return (
    <div className="mkt-ring" ref={hostRef}>
      <Image
        className="mkt-ring-poster"
        data-swapped={swapped ? "true" : "false"}
        src={poster}
        alt={label}
        width={1240}
        height={1240}
        priority
        sizes="(max-width: 767px) 92vw, 46vw"
      />
      {Ring ? <Ring tiles={tiles} onReady={() => setSwapped(true)} /> : null}
    </div>
  );
}

export default HeroRing;
