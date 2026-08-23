// /narxlar — full transparency: every tier, what it contains, the comparison,
// and the five questions people actually ask about money.

import type { Metadata } from "next";
import { Faq } from "@/components/marketing/faq";
import { ROUTES, SOCIAL, startHref } from "@/components/marketing/links";
import { TierCards, TierTable } from "@/components/marketing/pricing-cards";
import { FREE_CREDIT, soum } from "@/components/marketing/pricing-data";
import { ArrowLink, Band, CloseCta, PageHero, SectionHead } from "@/components/marketing/section";

export const metadata: Metadata = {
  title: "Narxlar",
  description:
    "Taqdimot paketlari: 5 000, 10 000 va 15 000 so‘m. Har bir paketda nima borligi, tahrirlar soni va to‘lov tartibi ochiq yozilgan.",
};

const PRICING_FAQ = [
  {
    q: "To‘lovni qanday qilaman?",
    a: (
      <>
        Hozircha hisobni Telegram bot orqali to‘ldirasiz: bot to‘lov havolasini beradi, mablag‘
        hisobingizga tushadi va har bir buyurtma o‘shandan yechiladi. Saytdagi to‘lov sahifasi
        keyingi bosqichda ochiladi.
      </>
    ),
  },
  {
    q: "“Tahrir” nima hisoblanadi?",
    a: (
      <>
        Tayyor taqdimotni qayta yig‘dirish so‘rovi: bir slaydni almashtirish, matnni qisqartirish,
        boshqa vizual so‘rash. Har bir paket bilan belgilangan sondagi tahrir keladi — Oddiy bilan
        bitta, Standart bilan ikkita, Premium bilan uchta. Tahrir muvaffaqiyatli tugagandagina
        hisobdan chiqadi.
      </>
    ),
  },
  {
    q: "Ish chiqmasa, pul yechiladimi?",
    a: (
      <>
        Yo‘q. Buyurtma xatolik bilan tugasa, mablag‘ hisobingizga qaytariladi — bu tizim
        darajasidagi qoida, iltimosnoma emas.
      </>
    ),
  },
  {
    q: "Bepul kredit qanday ishlaydi?",
    a: (
      <>
        Manba yuklash va savollarga javob berish kabi tadqiqot ishlari uchun bepul kredit
        beriladi: bittasi {soum(FREE_CREDIT.value)} qiymatida. Chegara — kuniga{" "}
        {FREE_CREDIT.dailyCap} ta, haftasiga {FREE_CREDIT.weeklyCap} ta va bitta loyihaga{" "}
        {FREE_CREDIT.projectCap} ta.
      </>
    ),
  },
  {
    q: "Nega AI rasmlar alohida hisoblanadi?",
    a: (
      <>
        Har bir rasm alohida xarajat. Shuning uchun paketlar rasm soni bilan farqlanadi: Oddiy
        paketda rasm yo‘q — uning o‘rniga tipografiya, gradient va geometrik naqsh ishlaydi.
      </>
    ),
  },
];

export default function PricingPage() {
  return (
    <>
      <PageHero
        eyebrow="Narxlar"
        title="Nima uchun to‘layotganingiz ochiq yozilgan"
        lede="Uchta paket, bitta farq: nechta AI rasm va nechta tahrir. Manbaga bog‘lash, provenans va uchala format hamma paketda bor."
      />

      <Band tight>
        <TierCards ctaLabel="Shu paket bilan boshlash" />
      </Band>

      <Band tone="inset" tight>
        <SectionHead folio="I." title="To‘liq taqqoslash" />
        <TierTable />
      </Band>

      <Band tight>
        <SectionHead
          folio="II."
          title="To‘lov va hisob"
          lede="Hisob mablag‘ bilan to‘ldiriladi, buyurtma esa o‘sha hisobdan yechiladi. Ish chiqmasa, mablag‘ qaytariladi."
        />
        <Faq items={PRICING_FAQ} />
        <p className="mkt-caption">
          Savolingiz ro‘yxatda yo‘qmi?{" "}
          <a href={SOCIAL.telegram} target="_blank" rel="noreferrer">
            Telegramda yozing
          </a>
          , yoki <ArrowLink href={ROUTES.help}>yordam bo‘limiga qarang</ArrowLink>
        </p>
      </Band>

      <CloseCta
        line="Bitta taqdimot — bitta narx."
        sub="Hisobingizni to‘ldirib, birinchi ishni bugun boshlang."
        primaryHref={startHref()}
        primaryLabel="Boshlash"
        secondaryHref={ROUTES.presentations}
        secondaryLabel="Qanday ishlaydi"
      />
    </>
  );
}
