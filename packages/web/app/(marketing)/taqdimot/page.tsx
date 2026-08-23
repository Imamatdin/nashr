// /taqdimot — the presentations product page. Claim, visual, repeat.

import type { Metadata } from "next";
import Link from "next/link";
import { AssetSlot } from "@/components/marketing/asset-slot";
import { startHref, ROUTES } from "@/components/marketing/links";
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
    "Yuklangan manbadan chiqqan taqdimot: har bir da’vo hujjatning aniq bo‘lagiga bog‘lanadi. HTML, PDF va PPTX bitta buyurtmadan.",
};

const FORMATS = [
  {
    key: "html",
    n: "HTML",
    title: "Interaktiv",
    body: "Brauzerda ochiladi, klaviatura bilan boshqariladi, savol-javob slaydlari ishlaydi. Bitta fayl — internetsiz ham ochiladi.",
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
        eyebrow="Taqdimot"
        title="Manbadan chiqqan taqdimot"
        lede="Hujjatlaringizni yuklaysiz — Nashr ulardan taqdimot yig‘adi. Slaydga chiqqan har bir raqam, ta’rif va iqtibos siz bergan hujjatning aniq bo‘lagidan keladi."
      >
        <Link href={startHref()} className="mkt-btn mkt-btn-lg">
          Boshlash
        </Link>
        <ArrowLink href={ROUTES.pricing}>Narxlarni ko‘rish</ArrowLink>
      </PageHero>

      <Band tight ruled>
        <SectionHead
          folio="I."
          title="Manba — boshlanish nuqtasi"
          lede="PDF, DOCX, PPTX, jadval yoki rasm. Fayl avval turini aniqlash tekshiruvidan o‘tadi, so‘ng bo‘laklarga ajratiladi: dvigatel keyin aynan shu bo‘laklarga iqtibos qiladi."
        />
        <AssetSlot
          label="Ish stolida manba yuklanmoqda: fayl ro‘yxati va ajratilgan bo‘laklar"
          note="Asset: public/marketing/shots/sources.png — muallif taqdim etadi"
          url="nashr.uz/new"
        />
      </Band>

      <Band tight>
        {/* COPY:FOUNDER — mexanizm bloklari: uchta da’vo, har biriga bitta vizual */}
        <FounderCopy>
          <Claim
            folio="II."
            title="Savol beriladi, keyin yoziladi"
            body={[
              "Dvigatel mavzuni o‘zicha to‘ldirmaydi. Manbada yetishmayotgan joy bo‘lsa, u siz bilan aniqlashtiradi va javobingiz ishga kiradi.",
              "Bu blok muallif matnini kutmoqda: intervyu bosqichi nima so‘raydi va javob taqdimotni qanday o‘zgartiradi.",
            ]}
            visual={
              <AssetSlot
                label="Ish stoli: dvigatel savol beradi, javob dalil sifatida saqlanadi"
                note="Asset: public/marketing/shots/interview.png"
                url="nashr.uz/projects/…"
              />
            }
          />
        </FounderCopy>

        <Claim
          folio="III."
          title="Har bir slayd o‘z manbasini olib yuradi"
          flip
          body={[
            "Tayyor ishda har bir da’vo yonida uning manbasi turadi: qaysi hujjat, qaysi bo‘lak, qanday iqtibos. Ustoz so‘raganda ochib ko‘rsatasiz.",
            "Manbada bo‘lmagan raqam yoki mavjud bo‘lmagan adabiyot chiqishga yetib bormaydi — ichki tekshiruv uni qaytaradi.",
          ]}
          note="Provenans ro‘yxati loyiha sahifasida ochiq turadi va ulashish havolasi bilan birga yuboriladi."
          visual={
            <AssetSlot
              label="Provenans jadvali: da’vo, iqtibos, manba fayli va bo‘lak raqami"
              note="Asset: public/marketing/shots/provenance.png"
              url="nashr.uz/projects/…"
            />
          }
        />

        <Claim
          folio="IV."
          title="Tahrir suhbat orqali"
          body={[
            "Tayyor taqdimotni qayta buyurtma qilmaysiz: nima o‘zgarishi kerakligini yozasiz va dvigatel o‘sha joyni qayta yig‘adi.",
            "Har bir paket bilan bir nechta tahrir keladi — Oddiy bilan bitta, Premium bilan uchta.",
          ]}
          visual={
            <AssetSlot
              label="Ish stoli: tahrir so‘rovi va qayta yig‘ilgan slayd"
              note="Asset: public/marketing/shots/fix.png"
              url="nashr.uz/projects/…"
            />
          }
        />
      </Band>

      <Band tone="inset" tight>
        <SectionHead
          folio="V."
          title="Uchala format ham asosiy"
          lede="Biri ikkinchisining o‘rnini bosuvchi emas: bitta ishdan uchala fayl ham chiqadi va yuklab olish havolalari yetti kun amal qiladi."
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
        <SectionHead
          folio="VI."
          title="Namunalar"
          lede="Dvigatelning haqiqiy chiqishi — qo‘l tegmagan holda."
        />
        <div className="mkt-pair">
          <AssetSlot
            variant="plate"
            label="Namuna taqdimot: muqova va bitta ma’lumot slaydi"
            note="Asset: public/marketing/decks/example-1.png"
          />
          <AssetSlot
            variant="plate"
            label="Namuna taqdimot: interaktiv savol slaydi"
            note="Asset: public/marketing/decks/example-2.png"
          />
        </div>
      </Band>

      <Band tight ruled>
        <SectionHead folio="VII." title="Paketlar" lede="Farq faqat AI rasmlar soni va tahrirlar sonida. Manbaga bog‘lash va uchala format hamma paketda bor." />
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
