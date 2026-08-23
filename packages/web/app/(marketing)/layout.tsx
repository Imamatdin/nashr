// The marketing route group. Light permanently — the site has no theme toggle
// and a dark-preference visitor gets the same paper ground (marketing.css pins
// the document itself). Server component: the interior pages render with no
// client bundle at all.
//
// "/" is not in this group: it stays at app/page.tsx and wraps itself in the
// same MarketingShell, so the two entry points cannot drift.

import type { Metadata } from "next";
import type { ReactNode } from "react";
import { MarketingShell } from "@/components/marketing/shell";

export const metadata: Metadata = {
  title: {
    default: "Nashr — manbaga asoslangan taqdimotlar",
    template: "%s — Nashr",
  },
};

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return <MarketingShell>{children}</MarketingShell>;
}
