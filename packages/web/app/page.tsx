// Landing — light permanently, Claude Design grammar: a centred serif claim,
// one accent fill, a real deck render under it, then hairline-separated
// blocks. Server component: nothing here holds state.

import {
  BarChart3,
  BookOpen,
  FileDown,
  FileText,
  GraduationCap,
  Link2,
  NotebookPen,
  Presentation,
  Quote,
  ShieldX,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import "./landing.css";

const DECKS = {
  criticalPoint: {
    src: "/decks/sco2-critical-point.jpg",
    alt: "Nashr dvigateli chiqargan slayd: 31°C va 73.8 bar chegarasi haqidagi sarlavha, to‘rtta dalil bandi va CO₂ ning faza diagrammasi",
  },
  integration: {
    src: "/decks/sco2-integration.jpg",
    alt: "Nashr dvigateli chiqargan slayd: sarlavha, izohli xatboshi va markazda chip, rack va inshoot halqalarini ko‘rsatuvchi doiraviy sxema",
  },
} as const;

const USES = [
  {
    icon: Presentation,
    title: "Taqdimot",
    soon: false,
    body: "Manbadan chiqqan slaydlar. HTML, PDF va PPTX bitta buyurtmadan.",
  },
  {
    icon: FileText,
    title: "Maqola",
    soon: true,
    body: "Dalil jadvali asosida bo‘lim-bo‘lim yoziladi, havolalari bilan.",
  },
  {
    icon: GraduationCap,
    title: "Dissertatsiya",
    soon: true,
    body: "Bob tuzilmasi, tayanch adabiyotlar va yagona iqtibos uslubi.",
  },
  {
    icon: NotebookPen,
    title: "Referat",
    soon: true,
    body: "Kirish, asosiy qism, xulosa. So‘ralgan hajmda, ortiqchasisiz.",
  },
  {
    icon: BookOpen,
    title: "Kurs ishi",
    soon: true,
    body: "Nazariy va amaliy boblar, ilovalar va adabiyotlar ro‘yxati.",
  },
  {
    icon: BarChart3,
    title: "Hisobot",
    soon: true,
    body: "Tahlil, natijalar va tavsiyalar aniq va tekshiriladigan tuzilmada.",
  },
] as const;

const MECHANISM = [
  {
    icon: Link2,
    label: "Da’vo manbaga bog‘lanadi",
    body: "Slaydga chiqqan har bir raqam, ta’rif va iqtibos siz yuklagan hujjatning aniq bo‘lagidan keladi. Bog‘lanmagan gap chiqishga yetib bormaydi.",
  },
  {
    icon: ShieldX,
    label: "Tanqidchi rad etadi",
    body: "Ichki tekshiruvchi manbada yo‘q raqamni yoki mavjud bo‘lmagan adabiyotni topsa, uni o‘tkazmaydi: bo‘limni qaytaradi va qayta yozdiradi.",
  },
  {
    icon: Quote,
    label: "Manba — bezak emas",
    body: "Har bir slayd o‘z manbasini yonida olib yuradi. Ustoz so‘raganda ochib ko‘rsatasiz, qayta izlab o‘tirmaysiz.",
  },
  {
    icon: FileDown,
    label: "Uch formatda olasiz",
    body: "HTML interaktiv brauzerda ochiladi, PDF chop etishga tayyor, PPTX PowerPointda tahrirlanadi. Uchalasi ham asosiy; biri ikkinchisining o‘rnini bosuvchi emas.",
  },
] as const;

const FLOW = [
  {
    title: "Telegramda yoki brauzerda boshlaysiz",
    body: "Mavzuni yozasiz yoki hujjatni tashlaysiz: PDF, DOCX, PPTX. Fayl avval tekshiruvdan o‘tadi.",
  },
  {
    title: "Ish stolida kuzatasiz",
    body: "Manbalar, ajratilgan bo‘laklar va yig‘ilayotgan slaydlar ochiq turadi. Qaysi gap qayerdan kelgani ko‘rinadi.",
  },
  {
    title: "Uch formatda olasiz",
    body: "HTML, PDF va PPTX bitta ishdan chiqadi. Yuklab olish havolalari yetti kun amal qiladi.",
  },
] as const;

export default function LandingPage() {
  return (
    <div className="theme-light lp">
      <header className="lp-nav">
        <div className="lp-wrap lp-nav-inner">
          <Link href="/" className="lp-wordmark">
            Nashr
          </Link>
          <nav className="lp-nav-actions">
            <Link href="/login" className="lp-navlink">
              Kirish
            </Link>
            <Link href="/login" className="btn lp-btn-ink lp-pill">
              Boshlash
            </Link>
          </nav>
        </div>
      </header>

      <main>
        <section className="lp-wrap lp-hero">
          <p className="lp-eyebrow lp-rise">Manbaga asoslangan taqdimotlar</p>
          <h1 className="lp-title lp-rise lp-rise-2">
            Ma’ruzangiz savolga{" "}
            <span className="lp-verb">
              dosh beradimi?<span className="lp-cite">1</span>
            </span>
          </h1>
          <p className="lp-lede lp-rise lp-rise-3">
            Nashr har bir fikrni manbaga bog‘laydi. Ustoz so‘raganda — javob tayyor.
          </p>
          <div className="lp-cta lp-rise lp-rise-4">
            <Link href="/login" className="btn lp-btn-ink btn-lg">
              Boshlash
            </Link>
          </div>
        </section>

        <section className="lp-wrap">
          <figure className="lp-figure">
            <div className="lp-frame">
              <Image
                src={DECKS.criticalPoint.src}
                alt={DECKS.criticalPoint.alt}
                width={1467}
                height={825}
                sizes="(max-width: 1128px) 100vw, 1080px"
                priority
              />
            </div>
            <figcaption className="lp-footnote">
              <span className="lp-cite">1</span> Har bir slayd o‘z manbasiga havola qiladi — bu odob
              emas, dastur darajasidagi talab. Manbasiz da’vo Nashr uchun bilim emas.
            </figcaption>
          </figure>
        </section>

        <section className="lp-wrap lp-band">
          <h2 className="lp-band-head">Bitta dvigatel, oltita ish turi.</h2>
          <div className="lp-uses">
            {USES.map((use) => (
              <div key={use.title} className="lp-use">
                <use.icon className="lp-use-icon" size={18} strokeWidth={1.5} aria-hidden />
                <h3 className="lp-use-title">
                  {use.title}
                  {use.soon ? <span className="lp-chip">tez kunda</span> : null}
                </h3>
                <p className="lp-use-body">{use.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="lp-wrap lp-band">
          <h2 className="lp-band-head">Qoida dvigatelning o‘zida yozilgan.</h2>
          <div className="lp-rows">
            {MECHANISM.map((row) => (
              <div key={row.label} className="lp-row">
                <h3 className="lp-row-label">
                  <row.icon size={18} strokeWidth={1.5} aria-hidden />
                  {row.label}
                </h3>
                <p className="lp-row-body">{row.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="lp-wrap lp-shot-b">
          <figure className="lp-figure">
            <div className="lp-frame">
              <Image
                src={DECKS.integration.src}
                alt={DECKS.integration.alt}
                width={1467}
                height={825}
                sizes="(max-width: 1128px) 100vw, 1080px"
              />
            </div>
            <figcaption className="lp-caption">
              Nashr dvigatelining haqiqiy chiqishi — qo‘l tegmagan holda
            </figcaption>
          </figure>
        </section>

        <section className="lp-flow">
          <div className="lp-wrap lp-flow-inner">
            <p className="lp-flow-eyebrow">Qanday boshlanadi</p>
            <div className="lp-flow-steps">
              {FLOW.map((step) => (
                <div key={step.title}>
                  <h3 className="lp-step-title">{step.title}</h3>
                  <p className="lp-step-body">{step.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-wrap lp-close">
          <h2 className="lp-close-line">Savol baribir beriladi. Javob tayyor bo‘lsin.</h2>
          <div className="lp-cta">
            <Link href="/login" className="btn lp-btn-ink btn-lg">
              Boshlash
            </Link>
          </div>
        </section>
      </main>

      <footer className="lp-foot">
        <div className="lp-wrap lp-foot-inner">
          <span>© {new Date().getFullYear()} Nashr</span>
          <span>Manbaga asoslangan akademik nashriyot</span>
        </div>
      </footer>
    </div>
  );
}
