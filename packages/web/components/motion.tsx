"use client";

// §4 motion vocabulary — these primitives and NOTHING else. transform/opacity
// only; prefers-reduced-motion collapses every entrance to instant state.
// Driven by IntersectionObserver + the CSS keyframes in globals.css rather
// than a motion library: the landing is the only consumer, and the library's
// hydration cost was the page's largest main-thread block. Before hydration
// everything renders visible (SSR ships no hidden state); the observer only
// hides-then-reveals elements that are still below the fold at mount.

import Image from "next/image";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

type RevealState = "ssr" | "pending" | "in";

// Shared reveal driver: "ssr" until mount; elements already in view at mount
// stay visible with no entrance; below-fold elements hide ("pending") and
// animate ("in") on first viewport entry.
function useRevealOnce(amount: number): [React.RefObject<HTMLDivElement | null>, RevealState] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<RevealState>("ssr");
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const rect = node.getBoundingClientRect();
    if (rect.top < window.innerHeight && rect.bottom > 0) return;
    setState("pending");
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setState("in");
          observer.disconnect();
        }
      },
      { threshold: amount },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [amount]);
  return [ref, state];
}

const revealClass: Record<RevealState, string | undefined> = {
  ssr: undefined,
  pending: "ink-pending",
  in: "ink-in",
};

// §4.1 Ink-reveal: children enter opacity 0→1 + 12px rise, staggered 80ms —
// the page "gets written". Wrap a block; each InkLine inside is one stroke.
export function InkReveal({ children, delay = 0 }: { children: ReactNode; delay?: number }) {
  const [ref, state] = useRevealOnce(0.3);
  return (
    <div
      ref={ref}
      className={revealClass[state]}
      style={{ "--ink-delay": `${Math.round(delay * 1000)}ms` } as CSSProperties}
    >
      {children}
    </div>
  );
}

export function InkLine({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div className="ink-line" style={style}>
      {children}
    </div>
  );
}

// §4.2 Dither-in — the signature move. Two stacked layers: the coarse dither
// variant underneath (upscaled, pixelated), the full plate over it. On first
// viewport entry the full layer crossfades in over ~900ms in uneven opacity
// steps, so the image resolves the way ink dries rather than sliding in.
// Reduced motion: the full plate is simply there (stylesheet-enforced).
// `immediate` runs the crossfade from first paint instead of viewport entry —
// required for the hero plate, which must never blank the first viewport.
export function DitherPlate({
  src,
  dither,
  alt,
  width,
  height,
  sizes,
  priority = false,
  immediate = false,
}: {
  src: string;
  dither: string;
  alt: string;
  width: number;
  height: number;
  sizes?: string;
  priority?: boolean;
  immediate?: boolean;
}) {
  const [ref, state] = useRevealOnce(0.25);
  const fullLayerClass = immediate
    ? "plate-layer dither-in-css"
    : state === "pending"
      ? "plate-layer dither-pending"
      : state === "in"
        ? "plate-layer dither-in-view"
        : "plate-layer";
  return (
    <span
      ref={ref as React.RefObject<HTMLSpanElement | null>}
      className="plate-stack"
      style={{ aspectRatio: `${width} / ${height}` }}
    >
      <Image
        className="plate-layer pixelated"
        src={dither}
        alt=""
        aria-hidden
        width={width}
        height={height}
        sizes={sizes}
        priority={priority}
      />
      <span className={fullLayerClass}>
        <Image
          src={src}
          alt={alt}
          width={width}
          height={height}
          sizes={sizes}
          priority={priority}
          style={{ width: "100%", height: "auto", display: "block" }}
        />
      </span>
    </span>
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
// Reduced-motion users get the static plate; matchMedia resolves after mount
// so SSR and first client render agree.
export function TiltPlate({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
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
