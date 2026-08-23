// Layout primitives for the marketing pages. Everything here is a server
// component: the site is typography and rules, and none of it needs a runtime.

import Link from "next/link";
import type { ReactNode } from "react";

export function Band({
  children,
  tone = "paper",
  ruled = false,
  tight = false,
  id,
}: {
  children: ReactNode;
  tone?: "paper" | "inset";
  ruled?: boolean;
  tight?: boolean;
  id?: string;
}) {
  const classes = [
    tight ? "mkt-band-tight" : "mkt-band",
    tone === "inset" ? "mkt-inset" : "",
    ruled ? "mkt-ruled" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section id={id} className={classes}>
      <div className="mkt-wrap">{children}</div>
    </section>
  );
}

export function PageHero({
  eyebrow,
  title,
  lede,
  children,
}: {
  /** Only when it says something the headline does not. Usually it does not. */
  eyebrow?: string;
  title: ReactNode;
  lede?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="mkt-wrap mkt-phero">
      <p className="mkt-eyebrow mkt-rise">{eyebrow ? <span>{eyebrow}</span> : null}</p>
      <h1 className="mkt-page-title mkt-rise mkt-rise-2">{title}</h1>
      {lede ? <p className="mkt-lede mkt-rise mkt-rise-3">{lede}</p> : null}
      {children ? <div className="mkt-phero-cta mkt-rise mkt-rise-4">{children}</div> : null}
    </section>
  );
}

/**
 * A folio number is the manuscript motif, and it earns its place only where the
 * sections are genuinely a sequence. Numbering every section on every page is
 * decoration, and decoration that looks like structure is worse than neither.
 */
export function SectionHead({
  folio,
  title,
  lede,
}: {
  folio?: string;
  title: ReactNode;
  lede?: ReactNode;
}) {
  return (
    <div className="mkt-sec-head">
      {folio ? <span className="mkt-folio">{folio}</span> : null}
      <h2 className="mkt-sec-title">{title}</h2>
      {lede ? <p className="mkt-sec-lede">{lede}</p> : null}
    </div>
  );
}

/** One claim, one visual, repeat. The visual side takes any node. */
export function Claim({
  folio,
  title,
  body,
  note,
  visual,
  flip = false,
}: {
  folio?: string;
  title: ReactNode;
  body: ReadonlyArray<ReactNode>;
  note?: ReactNode;
  visual: ReactNode;
  flip?: boolean;
}) {
  return (
    <div className={flip ? "mkt-claim mkt-claim-flip" : "mkt-claim"}>
      <div className="mkt-claim-text">
        {folio ? <span className="mkt-folio">{folio}</span> : null}
        <h3 className="mkt-claim-title">{title}</h3>
        {body.map((paragraph, index) => (
          <p key={index} className="mkt-claim-body">
            {paragraph}
          </p>
        ))}
        {note ? <p className="mkt-claim-note">{note}</p> : null}
      </div>
      <div className="mkt-claim-visual">{visual}</div>
    </div>
  );
}

export interface CellEntry {
  key: string;
  n?: string;
  title: string;
  chip?: string;
  body: ReactNode;
}

export function CellGrid({
  cells,
  columns = 3,
}: {
  cells: ReadonlyArray<CellEntry>;
  columns?: 2 | 3;
}) {
  return (
    <div className={columns === 2 ? "mkt-grid mkt-grid-2" : "mkt-grid"}>
      {cells.map((cell) => (
        <div key={cell.key} className="mkt-cell">
          {cell.n ? <span className="mkt-cell-n">{cell.n}</span> : null}
          <h3 className="mkt-cell-title">
            {cell.title}
            {cell.chip ? <span className="mkt-chip">{cell.chip}</span> : null}
          </h3>
          <p className="mkt-cell-body">{cell.body}</p>
        </div>
      ))}
    </div>
  );
}

function Arrow() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

function isExternal(href: string): boolean {
  return href.startsWith("http");
}

/** next/link is for in-app routes; an outbound link is a plain anchor. */
function Anchor({
  href,
  className,
  children,
}: {
  href: string;
  className: string;
  children: ReactNode;
}) {
  if (isExternal(href)) {
    return (
      <a href={href} className={className} target="_blank" rel="noreferrer">
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}

export function ArrowLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Anchor href={href} className="mkt-linkarrow">
      {children}
      <Arrow />
    </Anchor>
  );
}

export function CloseCta({
  line,
  sub,
  primaryHref,
  primaryLabel,
  secondaryHref,
  secondaryLabel,
}: {
  line: ReactNode;
  sub?: ReactNode;
  primaryHref: string;
  primaryLabel: string;
  secondaryHref?: string;
  secondaryLabel?: string;
}) {
  return (
    <section className="mkt-wrap mkt-close mkt-ruled">
      <h2 className="mkt-close-line">{line}</h2>
      {sub ? <p className="mkt-close-sub">{sub}</p> : null}
      <div className="mkt-close-cta">
        <Anchor href={primaryHref} className="mkt-btn mkt-btn-lg">
          {primaryLabel}
        </Anchor>
        {secondaryHref && secondaryLabel ? (
          <Anchor href={secondaryHref} className="mkt-btn mkt-btn-lg mkt-btn-quiet">
            {secondaryLabel}
          </Anchor>
        ) : null}
      </div>
    </section>
  );
}

/**
 * A narrative block the founder and architect still have to write. The text
 * inside is short, real Uzbek that states what the block will say — never
 * lorem ipsum — and every use is marked in the source with a COPY:FOUNDER
 * comment so the outstanding set can be listed with one grep.
 */
export function FounderCopy({ children }: { children: ReactNode }) {
  return <div data-copy="founder">{children}</div>;
}
