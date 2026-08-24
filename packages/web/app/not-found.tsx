"use client";

// G41: the single CTA sent everyone to /projects, which bounces a signed-out
// visitor to /login and loses them at the door. Whether a session exists is a
// browser fact, so the first paint is the signed-out variant and the signed-in
// one swaps in after mount — a mismatch-free order, not a flash of the wrong
// destination for the user who is actually signed in.

import { useEffect, useState } from "react";
import Link from "next/link";
import { loadSession } from "@/lib/session";
import "./(app)/doors.css";

export default function NotFound() {
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    try {
      setSignedIn(loadSession() !== null);
    } catch {
      setSignedIn(false);
    }
  }, []);

  return (
    <div className="theme-light notfound-shell">
      <Link href="/" className="notfound-brand">
        Nashr
      </Link>
      <p className="notfound-code">404</p>
      <div className="notfound-rule" aria-hidden />
      <p className="notfound-msg">Bu sahifa nashrda yo&apos;q.</p>
      <div className="notfound-actions">
        {signedIn ? (
          <>
            <Link href="/projects" className="btn btn-primary">
              Loyihalarga qaytish
            </Link>
            <Link href="/" className="notfound-quiet">
              Bosh sahifa
            </Link>
          </>
        ) : (
          <>
            <Link href="/" className="btn btn-primary">
              Bosh sahifaga qaytish
            </Link>
            <Link href="/login" className="notfound-quiet">
              Kirish
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
