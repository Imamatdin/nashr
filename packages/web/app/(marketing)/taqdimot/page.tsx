// /taqdimot — the presentations product page. One claim, one visual, repeat.
// The folio numbers stay on this page only: here the sections really are a
// sequence, so the numbers carry information instead of decorating.

import type { Metadata } from "next";
import Link from "next/link";
import { AssetSlot } from "@/components/marketing/asset-slot";
import { ROUTES, startHref } from "@/components/marketing/links";
import { TierCards } from "@/components/marketing/pricing-cards";
import {
  ArrowLink,
  Band,
  CellGrid,
  Claim,
  CloseCta,
  FounderCopy,
  PageHero,
  SectionHead,
} from "@/components/marketing/section";

export const metadata: Metadata = {
  title: "Taqdimot",
  description:
    "Yuklangan hujjatdan chiqqan taqdimot. Har bir da’vo manba bo‘lagiga bog‘lanadi, HTML, PDF va PPTX bitta buyurtmadan chiqadi.",
};

const FORMATS = [
  {
    key: "html",
    n: "HTML",
    title: "Interaktiv",
    body: "Brauzerda ochiladi, klaviatura bilan boshqariladi, savol slaydlari ishlaydi. Bitta fayl, internetsiz ham ochiladi.",
  },
  {
    key: "pdf",
    n: "PDF",
    title: "Chop etishga",
    body: "Bosmaga tayyor, matni tanlanadi va qidiriladi. Interaktiv qismlar statik ro‘yxatga aylanadi.",
  },
  {
    key: "pptx",
    n: "PPTX",
    title: "PowerPointda",
    body: "Auditoriya kompyuterida ochilishi kerak bo‘lganda. Slaydlar HTML bilan bir xil ko‘rinadi.",
  },
] as const;

export default function PresentationsPage() {
  return (
    <>
      <PageHero
        title="Manbadan chiqqan taqdimot"
        lede="Hujjatlaringizni yuklaysiz, Nashr ulardan taqdimot yig‘adi. Slaydga chiqqan raqam, ta’rif va iqtibos siz bergan hujjatning aniq bo‘lagidan keladi."
      >
        <Link href={startHref()} className="mkt-btn mkt-btn-lg">
          Boshlash
        </Link>
        <ArrowLink href={ROUTES.pricing}>Narxlar</ArrowLink>
      </PageHero>

      <Band tight ruled>
        <Claim
          folio="I."
          title="Manbadan boshlanadi"
          body={[
            "PDF, DOCX, PPTX, jadval yoki rasm yuklaysiz. Fayl turi tekshiriladi, matn esa bo‘laklarga ajratiladi.",
            "Keyingi bosqichlar aynan shu bo‘laklarga murojaat qiladi. Bo‘lak bo‘lmasa, da’vo ham bo‘lmaydi.",
          ]}
          visual={
            <AssetSlot
              label="Manba yuklash ekrani: fayllar va ajratilgan bo‘laklar"
              note="Asset: public/marketing/shots/sources.png"
            />
          }
        />

        {/* COPY:FOUNDER — intervyu bosqichi: nima so‘raladi va javob nimani o‘zgartiradi */}
        <FounderCopy>
          <Claim
            folio="II."
            title="Savol beriladi"
            flip
            body={[
              "Manbada yetishmagan joy bo‘lsa, Nashr uni siz bilan aniqlashtiradi.",
              "Bu blok muallif matnini kutmoqda: qanday savollar beriladi va javob tayyor ishga qanday ta’sir qiladi.",
            ]}
            visual={
              <AssetSlot
                label="Savol-javob ekrani: savol va saqlangan javob"
                note="Asset: public/marketing/shots/interview.png"
              />
            }
          />
        </FounderCopy>

        <Claim
          folio="III."
          title="Manba slayd bilan birga yuradi"
          body={[
            "Tayyor ishda har bir da’vo yonida uning manbasi turadi: qaysi hujjat, qaysi bo‘lak, qanday iqtibos.",
            "Manbada yo‘q raqam yoki mavjud bo‘lmagan adabiyot chiqishga yetib bormaydi. Ichki tekshiruv uni qaytaradi.",
          ]}
          note="Manbalar ro‘yxati loyiha sahifasida ochiq turadi va ulashish havolasi bilan birga ketadi."
          visual={
            <AssetSlot
              label="Manbalar jadvali: da’vo, iqtibos, fayl nomi va bo‘lak raqami"
              note="Asset: public/marketing/shots/provenance.png"
            />
          }
        />

        <Claim
          folio="IV."
          title="Tahrir suhbat orqali"
          flip
          body={[
            "Tayyor taqdimotni qayta buyurtma qilmaysiz. Nima o‘zgarishi kerakligini yozasiz, Nashr o‘sha joyni qayta yig‘adi.",
            "Har bir paketda tahrirlar soni belgilangan: Oddiyda bitta, Standartda ikkita, Premiumda uchta.",
          ]}
          visual={
            <AssetSlot
              label="Tahrir so‘rovi va qayta yig‘ilgan slayd"
              note="Asset: public/marketing/shots/fix.png"
            />
          }
        />
      </Band>

      <Band tone="inset" tight>
        <SectionHead
          title="Uchala format ham asosiy"
          lede="Bitta ishdan uchala fayl chiqadi. Yuklab olish havolalari yetti kun amal qiladi."
        />
        <CellGrid
          cells={FORMATS.map((format) => ({
            key: format.key,
            n: format.n,
            title: format.title,
            body: format.body,
          }))}
        />
      </Band>

      <Band tight>
        <SectionHead title="Namunalar" lede="Nashr chiqargan ishlar, qo‘l tegmagan holda." />
        <div className="mkt-pair">
          <AssetSlot
            label="Namuna: muqova va ma’lumot slaydi"
            note="Asset: public/marketing/decks/example-1.png"
          />
          <AssetSlot
            label="Namuna: interaktiv savol slaydi"
            note="Asset: public/marketing/decks/example-2.png"
          />
        </div>
      </Band>

      <Band tight ruled>
        <SectionHead
          title="Paketlar"
          lede="Manbaga bog‘lash, manbalar ro‘yxati va uchala format hamma paketda bor."
        />
        <TierCards />
        <p className="mkt-caption">
          <ArrowLink href={ROUTES.pricing}>To‘liq taqqoslash va savollar</ArrowLink>
        </p>
      </Band>

      <CloseCta
        line="Savol baribir beriladi. Javob tayyor bo‘lsin."
        primaryHref={startHref()}
        primaryLabel="Boshlash"
        secondaryHref={ROUTES.pricing}
        secondaryLabel="Narxlar"
      />
    </>
  );
}
