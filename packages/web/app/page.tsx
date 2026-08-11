// Landing (P3.5): what Nashr is, a CSS-drawn deck hero, login CTA.
// Static and server-rendered — no client JS beyond the shared chrome.

import Link from "next/link";

const FEATURES = [
  {
    icon: "📄",
    title: "Manbadan boshlanadi",
    text: "PDF yoki maqolangizni yuklaysiz — har bir slayd faqat o'sha manbadagi faktlarga tayanadi. To'qib chiqarilgan iqtibos yo'q.",
  },
  {
    icon: "🎨",
    title: "Bir urinishda studiya sifati",
    text: "Rang, tipografika va kompozitsiya qoidalari tizimning ichiga qurilgan. Shablon emas — har mavzuga alohida dizayn yo'nalishi.",
  },
  {
    icon: "🔗",
    title: "Uch format, bitta havola",
    text: "Interaktiv HTML, PowerPoint va PDF birga yetkaziladi. Ommaviy havola bilan istalgan telefonda ochiladi.",
  },
];

export default function LandingPage() {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="container topbar-inner">
          <span className="wordmark">Nashr</span>
          <nav className="nav-links">
            <Link href="/login" className="btn btn-primary">
              Kirish
            </Link>
          </nav>
        </div>
      </header>

      <main className="page">
        <div className="container">
          <section className="hero">
            <div>
              <h1>Manbangizdan ma'ruzagacha — bir qadam.</h1>
              <p className="hero-sub">
                Nashr yuklangan ilmiy manbalardan taqdimot yasaydi: dalillar manbadan olinadi,
                dizayn studiya darajasida, natija birinchi urinishdayoq tayyor.
              </p>
              <div className="hero-actions">
                <Link href="/login" className="btn btn-primary btn-lg">
                  Boshlash
                </Link>
                <Link href="/login" className="btn btn-ghost btn-lg">
                  Kirish
                </Link>
              </div>
            </div>
            <div className="deck-mock" aria-hidden>
              <div className="mock-slide mock-slide-back" />
              <div className="mock-slide">
                <div className="mock-kicker" />
                <div className="mock-title" />
                <div className="mock-title-2" />
                <div className="mock-bars">
                  <div className="mock-bar" style={{ height: "45%" }} />
                  <div className="mock-bar" style={{ height: "70%" }} />
                  <div className="mock-bar mock-bar-hot" style={{ height: "100%" }} />
                  <div className="mock-bar" style={{ height: "58%" }} />
                  <div className="mock-bar" style={{ height: "80%" }} />
                </div>
              </div>
            </div>
          </section>

          <section className="feature-grid">
            {FEATURES.map((feature) => (
              <div key={feature.title} className="card">
                <div className="state-icon" aria-hidden>
                  {feature.icon}
                </div>
                <h3>{feature.title}</h3>
                <p style={{ color: "var(--muted)", marginBottom: 0 }}>{feature.text}</p>
              </div>
            ))}
          </section>
        </div>
      </main>

      <footer className="footer">
        <div className="container footer-inner">
          <span>© {new Date().getFullYear()} Nashr</span>
          <span>Manbaga asoslangan akademik nashrlar</span>
        </div>
      </footer>
    </div>
  );
}
