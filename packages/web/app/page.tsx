// The home page. Light permanently, Claude Design grammar: a serif claim, one
// accent fill, a real composer, and hairline-separated blocks under it. Section
// order is fixed: hero, proof, how it works, the differentiator, pricing,
// questions. Server component — the only client islands are the composer and
// the ring gate, and both load after the page is painted.
//
// "/" cannot live in the (marketing) route group: two files would claim the
// same route. It wraps itself in the same MarketingShell instead.

import { existsSync } from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import Link from "next/link";
import { AssetSlot } from "@/components/marketing/asset-slot";
import { Faq } from "@/components/marketing/faq";
import { ROUTES, startHref } from "@/components/marketing/links";
import { TierCards } from "@/components/marketing/pricing-cards";
import { PromptTeaser } from "@/components/marketing/prompt-teaser";
import { ProvenanceFigure } from "@/components/marketing/provenance-figure";
import { HeroRing } from "@/components/marketing/ring/hero-ring";
import { ArrowLink, Band, CloseCta, FounderCopy, SectionHead } from "@/components/marketing/section";
import { MarketingShell } from "@/components/marketing/shell";

export const metadata: Metadata = {
  title: "Nashr — manbaga asoslangan taqdimotlar",
  description:
    "Nashr har bir fikrni manbaga bog‘laydi: yuklangan hujjatlardan bir urinishda nashr sifatidagi taqdimot. HTML, PDF va PPTX — uchala format ham asosiy.",
};

const RING_SLOTS = 12;
const RING_DIR = path.join(process.cwd(), "public", "marketing", "ring");

// Read once at build: the founder drops 01.png … 12.png into public/marketing/
// ring/ and the next build picks them up. A slot without a file stays empty and
// the ring paints its own plate there, so the composition is never short.
function ringTiles(): string[] {
  return Array.from({ length: RING_SLOTS }, (_, index) => {
    const name = `${String(index + 1).padStart(2, "0")}.png`;
    return existsSync(path.join(RING_DIR, name)) ? `/marketing/ring/${name}` : "";
  });
}

const STEPS = [
  {
    key: "manba",
    n: "01",
    title: "Manba yuklaysiz",
    body: "PDF, DOCX, PPTX yoki rasm. Fayl tekshiruvdan o‘tadi va bo‘laklarga ajratiladi.",
    slot: "Manba yuklash: fayllar ro‘yxati va tekshiruv holati",
    file: "public/marketing/shots/step-sources.png",
  },
  {
    key: "savol",
    n: "02",
    title: "Savollarga javob berasiz",
    body: "Dvigatel yetishmayotgan joyni so‘raydi. Javobingiz dalil sifatida ishga kiradi.",
    slot: "Savol-javob: dvigatel so‘raydi, javob saqlanadi",
    file: "public/marketing/shots/step-interview.png",
  },
  {
    key: "taqdimot",
    n: "03",
    title: "Dalilga tayangan taqdimot olasiz",
    body: "HTML, PDF va PPTX bitta ishdan chiqadi — har bir slayd manbasi bilan.",
    slot: "Tayyor taqdimot: slayd va uning manbasi",
    file: "public/marketing/shots/step-deck.png",
  },
] as const;

const FAQ = [
  {
    q: "Bu aldash emasmi?",
    a: (
      <>
        Nashr siz o‘rningizga o‘ylab bermaydi: u faqat siz bergan manbadan yozadi va har bir gapning
        qayerdan kelganini ko‘rsatadi. Ishni topshirish va uning mazmuni uchun javobgarlik sizda
        qoladi.
      </>
    ),
  },
  {
    q: "Manbam bo‘lmasa nima bo‘ladi?",
    a: (
      <>
        Manbasiz ish boshlanmaydi. Hujjatingiz bo‘lmasa, avval uni yuklang — dvigatel o‘zidan dalil
        to‘qimaydi.
      </>
    ),
  },
  {
    q: "Qaysi tillarda ishlaydi?",
    a: <>O‘zbekcha, qoraqalpoqcha, ruscha va inglizcha.</>,
  },
  {
    q: "Qanday fayllar chiqadi?",
    a: (
      <>
        Uchtasi ham: interaktiv HTML, chop etishga tayyor PDF va PowerPointda ochiladigan PPTX.
        Yuklab olish havolasi yetti kun amal qiladi.
      </>
    ),
  },
  {
    q: "Narxi qancha?",
    a: (
      <>
        Bitta taqdimot 5 000 so‘mdan boshlanadi; farq AI rasmlar va tahrirlar sonida.{" "}
        <Link href={ROUTES.pricing}>Narxlar sahifasi</Link> hammasini ochiq yozadi.
      </>
    ),
  },
  {
    q: "Ustozim tekshira oladimi?",
    a: (
      <>
        Ha. Ulashish havolasini yuborasiz: ishni brauzerda ochadi va har bir da’vo yonida uning
        manbasini ko‘radi.
      </>
    ),
  },
];

export default function HomePage() {
  const tiles = ringTiles();

  return (
    <MarketingShell>
      <section className="mkt-wrap mkt-hero">
        <div className="mkt-hero-text">
          <h1 className="mkt-hero-title mkt-rise">
            Ma’ruzangiz savolga{" "}
            <span className="mkt-hero-verb">
              dosh beradimi?<span className="mkt-hero-cite">1</span>
            </span>
          </h1>
          <p className="mkt-hero-sub mkt-rise mkt-rise-2">
            Nashr har bir fikrni manbaga bog‘laydi. Ustoz so‘raganda — javob tayyor.
          </p>
          <div className="mkt-rise mkt-rise-3">
            <PromptTeaser />
          </div>
          <p className="mkt-hero-foot mkt-rise mkt-rise-4">
            <span className="mkt-hero-cite">1</span> Har bir slayd o‘z manbasiga havola qiladi — bu
            odob emas, dastur darajasidagi talab.
          </p>
        </div>

        <div className="mkt-hero-visual mkt-rise mkt-rise-2">
          <HeroRing
            tiles={tiles}
            poster="/marketing/ring/poster.png"
            label="Nashr chiqargan slaydlarning sekin aylanuvchi halqasi"
          />
        </div>
      </section>

      <Band tight ruled>
        <AssetSlot
          label="Ish stoli: manbalar chapda, yig‘ilayotgan taqdimot o‘ngda"
          note="Asset: public/marketing/proof-workspace.png — muallif Session W (P2) dan keyin beradi"
          url="nashr.uz/projects/…"
          caption="Ish stolida nima bo‘layotgani ochiq turadi: qaysi manba o‘qildi, qaysi slayd yig‘ildi."
        />
      </Band>

      <Band tone="inset" tight>
        <SectionHead folio="I." title="Uch qadam" />
        <div className="mkt-steps">
          {STEPS.map((step) => (
            <div key={step.key} className="mkt-step">
              <span className="mkt-step-n">{step.n}</span>
              <h3 className="mkt-step-title">{step.title}</h3>
              <p className="mkt-step-body">{step.body}</p>
              <AssetSlot
                variant="plate"
                ratio="16 / 10"
                label={step.slot}
                note={`Asset: ${step.file}`}
              />
            </div>
          ))}
        </div>
      </Band>

      <Band tight>
        <div className="mkt-claim">
          <div className="mkt-claim-text">
            <span className="mkt-folio">II.</span>
            <h2 className="mkt-claim-title">Nashr faqat siz bergan dalilga tayanadi.</h2>
            <p className="mkt-claim-body">
              Slaydga chiqqan har bir raqam, ta’rif va iqtibos yuklangan hujjatning aniq bo‘lagidan
              keladi. Bog‘lanmagan gap chiqishga yetib bormaydi.
            </p>
            <p className="mkt-claim-body">
              Ichki tekshiruvchi manbada yo‘q raqamni yoki mavjud bo‘lmagan adabiyotni topsa, uni
              o‘tkazmaydi: bo‘limni qaytaradi va qayta yozdiradi.
            </p>
            <p className="mkt-claim-note">
              <ArrowLink href={ROUTES.presentations}>Mexanizm qanday ishlaydi</ArrowLink>
            </p>
          </div>
          <div className="mkt-claim-visual">
            <ProvenanceFigure />
          </div>
        </div>
      </Band>

      <Band tone="inset" tight>
        <SectionHead
          folio="III."
          title="Narxlar"
          lede="Uchta paket, bitta farq: nechta AI rasm va nechta tahrir."
        />
        <TierCards />
        <p className="mkt-caption">
          <ArrowLink href={ROUTES.pricing}>To‘liq taqqoslash</ArrowLink>
        </p>
      </Band>

      <Band tight>
        <SectionHead folio="IV." title="Savollar" />
        {/* COPY:FOUNDER — javoblar muallif ko‘rigini kutmoqda, ayniqsa birinchisi */}
        <FounderCopy>
          <Faq items={FAQ} />
        </FounderCopy>
      </Band>

      <CloseCta
        line="Savol baribir beriladi. Javob tayyor bo‘lsin."
        primaryHref={startHref()}
        primaryLabel="Boshlash"
        secondaryHref={ROUTES.presentations}
        secondaryLabel="Qanday ishlaydi"
      />
    </MarketingShell>
  );
}
