"use client";

// The gate in front of the ring. The poster is the hero image and ships in the
// server HTML; the canvas is an upgrade that only downloads when every one of
// the budget's conditions holds — the viewport intersects, motion is welcome,
// the visitor is not on Save-Data, the screen is wide enough, and a 2D context
// exists at all. Anything short of that and the poster is the whole hero, with
// no ring module fetched.

import Image from "next/image";
import { useEffect, useRef, useState, type ComponentType } from "react";
import { afterLoadWhenIdle, motionEligible } from "../motion-gate";
import type { RingCanvasProps } from "./ring-canvas";

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
    if (!host || !motionEligible()) return;

    let cancelled = false;
    let cancelIdle: (() => void) | null = null;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        cancelIdle = afterLoadWhenIdle(() => {
          void import("./ring-canvas").then((module) => {
            if (!cancelled) setRing(() => module.default);
          });
        });
      },
      { rootMargin: "200px" },
    );
    observer.observe(host);

    return () => {
      cancelled = true;
      observer.disconnect();
      cancelIdle?.();
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
