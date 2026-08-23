"use client";

// The gate in front of the /maqola desk scene. Same contract as the hero ring:
// the poster ships in the server HTML, and three.js is fetched only for a
// visitor who clears every condition, WebGL included. A phone, a Save-Data
// visitor or anyone asking for reduced motion gets the poster and no three.js
// request at all.

import Image from "next/image";
import { useEffect, useRef, useState, type ComponentType } from "react";
import { afterLoadWhenIdle, motionEligible } from "./motion-gate";
import type { DeskSceneProps } from "./plate/desk-scene";

const POSTER = "/marketing/plates/desk-poster.png";
const LABEL = "Chiroq ostidagi qog‘oz dastasi: Nashr ish stolining plastikasi";

export function DeskPlate() {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [Scene, setScene] = useState<ComponentType<DeskSceneProps> | null>(null);
  const [swapped, setSwapped] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !motionEligible(true)) return;

    let cancelled = false;
    let cancelIdle: (() => void) | null = null;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        cancelIdle = afterLoadWhenIdle(() => {
          void import("./plate/desk-scene").then((module) => {
            if (!cancelled) setScene(() => module.default);
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
    <div className="mkt-plate" ref={hostRef}>
      <Image
        className="mkt-plate-poster"
        data-swapped={swapped ? "true" : "false"}
        src={POSTER}
        alt={LABEL}
        width={1100}
        height={1100}
        sizes="(max-width: 979px) 88vw, 42vw"
        priority
      />
      {Scene ? <Scene onReady={() => setSwapped(true)} /> : null}
    </div>
  );
}

export default DeskPlate;
