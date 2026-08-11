// Landing — gate (a) scope: tokens + type + the hero section only.
// Stakes first, then the mechanism as a footnote, then the plate.
// The engraving is a hand-drawn SVG armillary stand-in until the
// Higgsfield plates land (§5); the frame and caption are final.

import Link from "next/link";
import { GildOnView, InkLine, InkReveal, TiltPlate } from "@/components/motion";

export default function LandingPage() {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="container topbar-inner">
          <span className="wordmark">Nashr</span>
          <nav className="nav-links">
            <Link href="/login">Kirish</Link>
          </nav>
        </div>
      </header>

      <main className="page">
        <div className="container">
          <section className="grid items-center gap-14 py-8 md:grid-cols-[1.1fr_0.9fr] md:py-14">
            <InkReveal>
              <InkLine>
                <p className="folio">I.</p>
              </InkLine>
              <InkLine style={{ marginTop: "1rem" }}>
                <h1
                  className="font-display"
                  style={{ fontSize: "var(--text-hero)", maxWidth: "20ch", textWrap: "balance" }}
                >
                  Ma&rsquo;ruzangiz savolga{" "}
                  <em className="not-italic" style={{ color: "var(--zangori)" }}>
                    dosh beradimi?
                  </em>
                  <span className="cite-mark" style={{ fontSize: "0.3em" }}>
                    1
                  </span>
                </h1>
              </InkLine>
              <InkLine style={{ marginTop: "1.6rem" }}>
                <p className="max-w-[44ch] text-xl" style={{ color: "var(--ink-88)" }}>
                  Nashr har bir fikrni manbaga bog&rsquo;laydi. Ustoz so&rsquo;raganda —
                  javob tayyor.
                </p>
              </InkLine>
              <InkLine style={{ marginTop: "2.2rem" }}>
                <div className="flex flex-wrap items-center gap-6">
                  <GildOnView>
                    <span className="gild-underline inline-block">
                      <Link
                        href="/login"
                        className="inline-flex items-center px-7 py-3.5 font-semibold"
                        style={{
                          background: "var(--zangori)",
                          color: "var(--qogoz)",
                          borderRadius: "var(--radius)",
                        }}
                      >
                        Boshlash
                      </Link>
                    </span>
                  </GildOnView>
                  <Link href="/login" className="font-semibold">
                    A&rsquo;zo bo&rsquo;lganmisiz? Kirish
                  </Link>
                </div>
              </InkLine>
              <InkLine style={{ marginTop: "3.4rem" }}>
                <hr className="footnote" />
                <p className="footnote-text">
                  <span className="cite-mark" style={{ verticalAlign: "baseline" }}>
                    1
                  </span>{" "}
                  Har bir slayd o&rsquo;z manbasiga havola qiladi — bu odob emas,
                  dastur darajasidagi talab. Manbasiz da&rsquo;vo Nashr uchun
                  bilim emas.
                </p>
              </InkLine>
            </InkReveal>

            <InkReveal delay={0.25}>
              <InkLine>
                <TiltPlate>
                  <figure className="plate m-0">
                    <div className="dither flex items-center justify-center" aria-hidden>
                      <ArmillaryEngraving />
                    </div>
                    <figcaption className="plate-caption">
                      LAVHA I — FALAK O&rsquo;LCHOVI
                    </figcaption>
                  </figure>
                </TiltPlate>
              </InkLine>
            </InkReveal>
          </section>
        </div>
      </main>

      <footer className="footer">
        <div className="container footer-inner">
          <span>© {new Date().getFullYear()} Nashr</span>
          <span>Manbaga asoslangan akademik nashriyot</span>
        </div>
      </footer>
    </div>
  );
}

// Thin-stroke armillary sphere in the engraving language: ink lines only,
// no fills. Replaced by the Higgsfield Ulugh Beg plate at gate (b).
function ArmillaryEngraving() {
  const ink = "var(--siyoh)";
  return (
    <svg
      viewBox="0 0 520 460"
      role="img"
      aria-label="Armillar sfera — o'yma uslubida"
      style={{ width: "100%", maxWidth: 480, display: "block" }}
    >
      <g fill="none" stroke={ink} strokeWidth="1.1" opacity="0.82">
        {/* meridian rings */}
        <circle cx="260" cy="210" r="150" strokeWidth="1.6" />
        <ellipse cx="260" cy="210" rx="150" ry="52" />
        <ellipse cx="260" cy="210" rx="52" ry="150" />
        <ellipse cx="260" cy="210" rx="150" ry="104" opacity="0.5" />
        {/* ecliptic band, tilted */}
        <g transform="rotate(-23 260 210)">
          <ellipse cx="260" cy="210" rx="150" ry="30" strokeWidth="1.4" />
          <ellipse cx="260" cy="210" rx="150" ry="22" opacity="0.55" />
        </g>
        {/* polar axis */}
        <line x1="260" y1="18" x2="260" y2="402" strokeWidth="1.4" />
        <circle cx="260" cy="18" r="5" />
        <circle cx="260" cy="402" r="5" />
        {/* graduation ticks on the outer ring */}
        {Array.from({ length: 36 }, (_, i) => {
          const a = (i * 10 * Math.PI) / 180;
          const x1 = 260 + Math.cos(a) * 150;
          const y1 = 210 + Math.sin(a) * 150;
          const x2 = 260 + Math.cos(a) * (i % 3 === 0 ? 141 : 145);
          const y2 = 210 + Math.sin(a) * (i % 3 === 0 ? 141 : 145);
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth="1" />;
        })}
        {/* inner earth */}
        <circle cx="260" cy="210" r="14" strokeWidth="1.4" />
        <line x1="246" y1="210" x2="274" y2="210" opacity="0.7" />
        <line x1="260" y1="196" x2="260" y2="224" opacity="0.7" />
        {/* stand */}
        <path d="M 200 402 Q 260 380 320 402" strokeWidth="1.4" />
        <line x1="230" y1="440" x2="290" y2="440" strokeWidth="1.6" />
        <line x1="245" y1="402" x2="238" y2="440" />
        <line x1="275" y1="402" x2="282" y2="440" />
      </g>
    </svg>
  );
}
