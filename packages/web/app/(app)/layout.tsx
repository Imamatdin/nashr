// The app shell. Everything behind a door — the workspace, the composer, the
// folio, the ledger, the doors themselves — renders inside it.
//
// It exists to hold the theme. Both halves of the theme system used to live in
// the ROOT layout, which wraps the marketing site too, so every static
// marketing page shipped a ThemeProvider it never used and ran a no-flash
// script for a preference it never read. A route group changes no URL: these
// files still serve /projects, /new, /login and the rest.
//
// The no-flash script must run BEFORE this subtree paints, which is why it is
// an inline sync script at the top of the group rather than an effect: an
// effect runs after hydration, and the flash it exists to prevent has already
// happened by then.

import type { ReactNode } from "react";
import { ThemeProvider } from "@/components/theme-provider";
import { NO_FLASH_SCRIPT } from "@/lib/theme";

export default function AppGroupLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: NO_FLASH_SCRIPT }} />
      <ThemeProvider>{children}</ThemeProvider>
    </>
  );
}
