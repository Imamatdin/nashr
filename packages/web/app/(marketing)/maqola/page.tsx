// /maqola — the article product page. The revenue product, and the one that is
// not delivered yet: the page says so on the first screen rather than the last.

import type { Metadata } from "next";
import { AssetSlot } from "@/components/marketing/asset-slot";
import { DeskPlate } from "@/components/marketing/desk-plate";
import { ROUTES, startHref } from "@/components/marketing/links";
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
  title: "Maqola",
  description:
    "Dalil jadvaliga tayangan ilmiy matn. Har bir da’vo manbaga bog‘lanadi, iqtiboslar bitta uslubda rasmiylashtiriladi. Tez kunda.",
};

const STRUCTURES = [
  {
    key: "referat",
    title: "Referat",
    body: "Kirish, asosiy qism, xulosa va adabiyotlar ro‘yxati. So‘ralgan hajmda.",
  },
  {
    key: "kurs",
    title: "Kurs ishi",
    body: "Mundarija, nazariy bob, amaliy bob, xulosa, adabiyotlar va ilovalar.",
  },
  {
    key: "ilmiy",
    title: "Ilmiy maqola",
    body: "Annotatsiya, adabiyotlar sharhi, metodika, natijalar, muhokama va xulosa.",
  },
  {
    key: "hisobot",
    title: "Hisobot",
    body: "Kirish, tahlil, natijalar va tavsiyalar. Tekshirilishi mumkin bo‘lgan tuzilmada.",
  },
] as const;

export default function ArticlesPage() {
  return (
    <>
      <section className="mkt-wrap mkt-intro">
        <div className="mkt-intro-text">
          <p className="mkt-eyebrow mkt-rise">
            <span>Tez kunda</span>
          </p>
          <h1 className="mkt-page-title mkt-rise mkt-rise-2">Ish sizniki. Tuzilmani biz beramiz.</h1>
          <p className="mkt-lede mkt-rise mkt-rise-3">
            Maqola matni dalil jadvalidan o‘sadi. Avval qaysi da’vo qaysi manbaga tayanishi
            aniqlanadi, keyin bo‘limlar yoziladi. Manbasiz jumla matnga kirmaydi.
          </p>
          <div className="mkt-phero-cta mkt-rise mkt-rise-4">
            <ArrowLink href={ROUTES.presentations}>Hozircha taqdimotdan boshlang</ArrowLink>
          </div>
        </div>

        <div className="mkt-intro-visual mkt-rise mkt-rise-2">
          <DeskPlate />
        </div>
      </section>

      <Band tight ruled>
        <Claim
          title="Dalil jadvali"
          body={[
            "Maqolaning yadrosi matn emas, dalil jadvali. Har bir da’vo, uni tasdiqlovchi manba bo‘lagi va o‘sha bo‘lakdagi iqtibos bitta qatorda turadi.",
            "Bo‘limlar shu jadvaldan yoziladi. Qator bo‘sh bo‘lsa, da’vo matnga chiqmaydi va savol bo‘lib qoladi.",
          ]}
          visual={
            <AssetSlot
              label="Dalil jadvali: da’vo, manba, iqtibos va holat ustunlari"
              note="Asset: public/marketing/shots/evidence-matrix.png"
            />
          }
        />

        {/* COPY:FOUNDER — iqtibos intizomi: qaysi uslublar va ular qanday tekshiriladi */}
        <FounderCopy>
          <Claim
            title="Iqtibos intizomi"
            flip
            body={[
              "O‘zbek universitetlari talab qiladigan rasmiylashtirish qoidalari xalqaro jurnallarnikidan farq qiladi. Nashr ikkalasini ham biladi va tanlangan uslubga oxirigacha rioya qiladi.",
              "Bu blok muallif matnini kutmoqda: qaysi uslublar qo‘llab-quvvatlanadi va havolalar qanday tekshiriladi.",
            ]}
            visual={
              <AssetSlot
                label="Adabiyotlar ro‘yxati: bitta uslubda, matndagi havolalar bilan"
                note="Asset: public/marketing/shots/bibliography.png"
              />
            }
          />
        </FounderCopy>
      </Band>

      <Band tone="inset" tight>
        <SectionHead
          title="To‘rtta akademik tuzilma"
          lede="Har biri o‘z bo‘limlari va talablari bilan, universitet qabul qiladigan shaklda."
        />
        <CellGrid
          cells={STRUCTURES.map((entry) => ({
            key: entry.key,
            title: entry.title,
            body: entry.body,
          }))}
          columns={2}
        />
      </Band>

      <Band tight>
        <SectionHead title="Hozirgi holat" />
        <div className="mkt-prose">
          <p>
            Maqola dvigateli hali ochilmagan. Uni taqdimotlar bilan bir xil qoidada quramiz:
            manbasiz da’vo yo‘q, to‘qilgan adabiyot yo‘q. Ochilgan kuni shu sahifada yozib
            qo‘yamiz.
          </p>
          <p>
            Shu vaqtgacha taqdimot dvigateli ishlaydi va u ham shu qoidaga bo‘ysunadi. Mexanizmni
            o‘sha yerda ko‘rib olishingiz mumkin.
          </p>
        </div>
      </Band>

      <CloseCta
        line="Manba tayyor bo‘lsa, ish ham boshlanadi."
        sub="Maqola ochilgunicha taqdimotdan boshlang. Manbaga bog‘lash mexanizmi bir xil."
        primaryHref={startHref()}
        primaryLabel="Boshlash"
        secondaryHref={ROUTES.presentations}
        secondaryLabel="Taqdimot"
      />
    </>
  );
}
