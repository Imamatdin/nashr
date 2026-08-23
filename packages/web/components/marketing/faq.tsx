// FAQ on native <details>: open/close with zero client JavaScript, which is
// what keeps the interior pages at the Next.js baseline bundle.

import type { ReactNode } from "react";

export interface FaqEntry {
  q: string;
  a: ReactNode;
}

export function Faq({ items }: { items: ReadonlyArray<FaqEntry> }) {
  return (
    <div className="mkt-faq">
      {items.map((item) => (
        <details key={item.q} className="mkt-faq-item">
          <summary className="mkt-faq-q">{item.q}</summary>
          <div className="mkt-faq-a">{item.a}</div>
        </details>
      ))}
    </div>
  );
}

export default Faq;
