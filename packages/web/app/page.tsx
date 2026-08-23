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
  title: "Nashr: manbaga asoslangan taqdimotlar",
  description:
    "Nashr har bir fikrni manbaga bog‘laydi. Yuklangan hujjatlardan bir urinishda nashr sifatidagi taqdimot chiqadi: HTML, PDF va PPTX.",
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
    title: "Manba yuklaysiz",
    body: "PDF, DOCX, PPTX yoki rasm. Fayl tekshiruvdan o‘tadi va o‘qiladigan bo‘laklarga ajraladi.",
    slot: "Manba yuklash: fayllar ro‘yxati va tekshiruv holati",
    file: "public/marketing/shots/step-sources.png",
  },
  {
    key: "savol",
    title: "Savollarga javob berasiz",
    body: "Manbada yetishmagan joyni so‘raydi. Javobingiz keyingi bosqichda ishlatiladi.",
    slot: "Savol-javob ekrani: savol va saqlangan javob",
    file: "public/marketing/shots/step-interview.png",
  },
  {
    key: "taqdimot",
    title: "Dalilga tayangan taqdimot olasiz",
    body: "Bitta ishdan HTML, PDF va PPTX chiqadi. Har bir slayd o‘z manbasini ko‘rsatadi.",
    slot: "Tayyor taqdimot va uning manbalar ro‘yxati",
    file: "public/marketing/shots/step-deck.png",
  },
] as const;

const FAQ = [
  {
    q: "Bu aldash emasmi?",
    a: (
      <>
        Nashr siz uchun o‘ylab qo‘ymaydi. U faqat siz yuklagan hujjatdan yozadi va har bir gapning
        qayerdan kelganini ochiq ko‘rsatadi, shuning uchun uni tekshirish ham oson. Topshirilgan
        ish uchun javobgarlik sizda qoladi.
      </>
    ),
  },
  {
    q: "Manbam bo‘lmasa nima bo‘ladi?",
    a: (
      <>
        Manbasiz ish boshlanmaydi. Nashr o‘zidan dalil to‘qimaydi, shuning uchun avval hujjat
        kerak: ma’ruza matni, maqola, kitob bobi yoki hisobot.
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
        Interaktiv HTML, chop etishga tayyor PDF va PowerPointda ochiladigan PPTX. Yuklab olish
        havolasi yetti kun amal qiladi.
      </>
    ),
  },
  {
    q: "Narxi qancha?",
    a: (
      <>
        Bitta taqdimot 5 000 so‘mdan boshlanadi. Paketlar faqat AI rasmlar va tahrirlar soni bilan
        farq qiladi, buni <Link href={ROUTES.pricing}>narxlar sahifasi</Link> to‘liq yozib qo‘ygan.
      </>
    ),
  },
  {
    q: "Ustozim tekshira oladimi?",
    a: (
      <>
        Ha. Unga ulashish havolasini yuborasiz. Havola ishni brauzerda ochadi va har bir da’vo
        yonida uning manbasi turadi.
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
            Nashr har bir fikrni manbaga bog‘laydi. Ustoz so‘raganda javob tayyor turadi.
          </p>
          <div className="mkt-rise mkt-rise-3">
            <PromptTeaser />
          </div>
          <p className="mkt-hero-foot mkt-rise mkt-rise-4">
            <span className="mkt-hero-cite">1</span> Har bir slayd qaysi hujjatning qaysi
            bo‘lagidan chiqqanini ko‘rsatadi.
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
          note="Asset: public/marketing/proof-workspace.png"
          caption="Manbalar, ajratilgan bo‘laklar va yig‘ilayotgan slaydlar bitta ekranda turadi."
        />
      </Band>

      <Band tone="inset" tight>
        <SectionHead title="Uch qadam" />
        <div className="mkt-steps">
          {STEPS.map((step) => (
            <div key={step.key} className="mkt-step">
              <h3 className="mkt-step-title">{step.title}</h3>
              <p className="mkt-step-body">{step.body}</p>
              <AssetSlot ratio="16 / 10" label={step.slot} note={"Asset: " + step.file} />
            </div>
          ))}
        </div>
      </Band>

      <Band tight>
        <div className="mkt-claim">
          <div className="mkt-claim-text">
            <h2 className="mkt-claim-title">Nashr faqat siz bergan dalilga tayanadi.</h2>
            <p className="mkt-claim-body">
              Slaydga chiqqan raqam, ta’rif va iqtibos yuklangan hujjatning aniq bo‘lagidan keladi.
              Manbaga bog‘lanmagan gap chiqishga yetib bormaydi.
            </p>
            <p className="mkt-claim-body">
              Ichki tekshiruvchi manbada yo‘q raqamni yoki mavjud bo‘lmagan adabiyotni topsa,
              bo‘limni qaytaradi va qayta yozdiradi.
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
        <SectionHead title="Narxlar" lede="Uchta paket. Farq faqat AI rasmlar va tahrirlar sonida." />
        <TierCards />
        <p className="mkt-caption">
          <ArrowLink href={ROUTES.pricing}>To‘liq taqqoslash</ArrowLink>
        </p>
      </Band>

      <Band tight>
        <SectionHead title="Savollar" />
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
