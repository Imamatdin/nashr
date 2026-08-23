// /yordam — the questions a first-time user actually has, answered in one line
// each. Zero client JS: the accordion is native <details>.

import type { Metadata } from "next";
import { Faq } from "@/components/marketing/faq";
import { ROUTES, SOCIAL, startHref } from "@/components/marketing/links";
import { Band, CloseCta, PageHero, SectionHead } from "@/components/marketing/section";

export const metadata: Metadata = {
  title: "Yordam",
  description:
    "Nashr bilan ishlash bo‘yicha savollar: qanday boshlash, qanday fayllar mumkin, formatlar, tahrir va to‘lov.",
};

const START = [
  {
    q: "Qanday boshlanadi?",
    a: (
      <>
        Kirasiz, mavzuni yozasiz va manba hujjatlaringizni biriktirasiz. Buyurtma tasdiqlangach ish
        boshlanadi va uni ish stolida kuzatasiz.
      </>
    ),
  },
  {
    q: "Qanday fayllarni yuklash mumkin?",
    a: <>PDF, DOCX, PPTX, XLSX, matn va jadval fayllari, hamda rasmlar (PNG, JPG, WEBP, GIF).</>,
  },
  {
    q: "Qaysi tillarda ishlaydi?",
    a: <>O‘zbekcha, qoraqalpoqcha, ruscha va inglizcha. Tilni buyurtma berishda tanlaysiz.</>,
  },
];

const OUTPUT = [
  {
    q: "Qanday fayllar chiqadi?",
    a: (
      <>
        Bitta ishdan uchtasi ham: brauzerda ochiladigan interaktiv HTML, chop etishga tayyor PDF va
        PowerPointda ochiladigan PPTX.
      </>
    ),
  },
  {
    q: "Yuklab olish havolasi qancha turadi?",
    a: <>Yetti kun. Muddat tugasa, loyihadan qayta yuklab olasiz.</>,
  },
  {
    q: "Ishni boshqalarga qanday ko‘rsataman?",
    a: (
      <>
        Loyihadan ulashish havolasini olasiz. Havolani ochgan odam taqdimotni brauzerda ko‘radi;
        tahrirlay olmaydi.
      </>
    ),
  },
  {
    q: "Natija yoqmasa nima qilaman?",
    a: (
      <>
        Nima o‘zgarishi kerakligini yozasiz va dvigatel o‘sha joyni qayta yig‘adi. Har bir paketda
        belgilangan sondagi tahrir bor.
      </>
    ),
  },
];

const MONEY = [
  {
    q: "To‘lov qanday amalga oshadi?",
    a: (
      <>
        Hozircha hisobni Telegram bot orqali to‘ldirasiz; har bir buyurtma shu hisobdan yechiladi.
      </>
    ),
  },
  {
    q: "Ish xato bilan tugasa-chi?",
    a: <>Mablag‘ hisobingizga qaytariladi.</>,
  },
];

export default function HelpPage() {
  return (
    <>
      <PageHero
        eyebrow="Yordam"
        title="Savollar va javoblar"
        lede="Ko‘p so‘raladigan savollar. Ro‘yxatda yo‘q savolni Telegramda yozsangiz, javob beramiz."
      />

      <Band tight ruled>
        <SectionHead folio="I." title="Boshlash" />
        <Faq items={START} />
      </Band>

      <Band tight>
        <SectionHead folio="II." title="Natija va formatlar" />
        <Faq items={OUTPUT} />
      </Band>

      <Band tone="inset" tight>
        <SectionHead folio="III." title="To‘lov" />
        <Faq items={MONEY} />
        <p className="mkt-caption">
          Batafsil:{" "}
          <a href={ROUTES.pricing} className="mkt-navlink">
            narxlar sahifasi
          </a>
        </p>
      </Band>

      <CloseCta
        line="Javob topilmadimi?"
        sub="Telegramda yozing — odam javob beradi."
        primaryHref={SOCIAL.telegram}
        primaryLabel="Telegramda yozish"
        secondaryHref={startHref()}
        secondaryLabel="Boshlash"
      />
    </>
  );
}
