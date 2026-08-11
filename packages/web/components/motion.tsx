"use client";

// §4 motion vocabulary — these primitives and NOTHING else. transform/opacity
// only; prefers-reduced-motion collapses every entrance to instant state.

import { LazyMotion, domAnimation, m, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

// §4.1 Ink-reveal: children enter opacity 0→1 + 12px rise, staggered 80ms —
// the page "gets written". Wrap a block; each InkLine inside is one stroke.
export function InkReveal({ children, delay = 0 }: { children: ReactNode; delay?: number }) {
  const reduced = useReducedMotion();
  return (
    <LazyMotion features={domAnimation} strict>
      <m.div
        initial={reduced ? false : "hidden"}
        whileInView="shown"
        viewport={{ once: true, amount: 0.3 }}
        transition={{ staggerChildren: 0.08, delayChildren: delay }}
      >
        {children}
      </m.div>
    </LazyMotion>
  );
}

export function InkLine({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <m.div
      style={style}
      variants={{
        hidden: { opacity: 0, y: 12 },
        shown: { opacity: 1, y: 0, transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] } },
      }}
    >
      {children}
    </m.div>
  );
}

// §4.3 The gilded moment: adds the `gilded` class once on first viewport
// entry, which draws the gold underline of any `.gild-underline` child.
export function GildOnView({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [gilded, setGilded] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setGilded(true);
          observer.disconnect();
        }
      },
      { threshold: 0.6 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return (
    <div ref={ref} className={gilded ? "gilded" : undefined}>
      {children}
    </div>
  );
}

// §4.4 Deck plates: tilt ≤2deg toward the pointer, shadow deepens. No 3D.
export function TiltPlate({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement | null>(null);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  if (reduced) return <div>{children}</div>;
  return (
    <div
      ref={ref}
      onMouseMove={(event) => {
        const rect = ref.current?.getBoundingClientRect();
        if (!rect) return;
        const px = (event.clientX - rect.left) / rect.width - 0.5;
        const py = (event.clientY - rect.top) / rect.height - 0.5;
        setTilt({ x: py * -2, y: px * 2 });
      }}
      onMouseLeave={() => setTilt({ x: 0, y: 0 })}
      style={{
        transform: `perspective(1200px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
        transition: "transform 180ms ease-out",
        willChange: "transform",
      }}
    >
      {children}
    </div>
  );
}
