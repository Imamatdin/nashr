"use client";

// Ported from beautifului.dev "prompt-bar" (MIT), extracted as a primitive.
// Kept: the rowBox + useLayoutEffect measurement (offsetTop / offsetHeight),
// the single absolutely positioned highlight, and the 220ms glide easing.
// Replaced: the menu-specific `active`/`engaged` state with pointer + focus
// delegation over an arbitrary row selector.

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

type Box = { top: number; height: number };

const GLIDE_TRANSITION =
  "top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease";

export default function GlideMenu({
  children,
  className,
  highlightClassName,
  rowSelector = "[data-menu-row]",
}: {
  children: ReactNode;
  className?: string;
  highlightClassName?: string;
  rowSelector?: string;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const rowRef = useRef<HTMLElement | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  const [engaged, setEngaged] = useState(false);

  const measure = useCallback(() => {
    const row = rowRef.current;
    if (!row || !wrapRef.current?.contains(row)) return;
    setBox({ top: row.offsetTop, height: row.offsetHeight });
  }, []);

  const engage = useCallback(
    (target: EventTarget | null) => {
      if (!(target instanceof Element)) return;
      const row = target.closest<HTMLElement>(rowSelector);
      if (!row || !wrapRef.current?.contains(row)) return;
      rowRef.current = row;
      setBox({ top: row.offsetTop, height: row.offsetHeight });
      setEngaged(true);
    },
    [rowSelector],
  );

  useLayoutEffect(measure, [measure, children]);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [measure]);

  return (
    <div
      ref={wrapRef}
      className={className ? `relative ${className}` : "relative"}
      onPointerOver={(event) => engage(event.target)}
      onPointerLeave={() => setEngaged(false)}
      onFocusCapture={(event) => engage(event.target)}
      onBlurCapture={(event) => {
        if (!event.relatedTarget || !wrapRef.current?.contains(event.relatedTarget)) {
          setEngaged(false);
        }
      }}
    >
      <span
        aria-hidden
        className={
          highlightClassName
            ? `pointer-events-none absolute z-0 ${highlightClassName}`
            : "pointer-events-none absolute z-0"
        }
        style={{
          top: box?.top ?? 0,
          height: box?.height ?? 0,
          opacity: box && engaged ? 1 : 0,
          transition: GLIDE_TRANSITION,
        }}
      />
      {children}
    </div>
  );
}
