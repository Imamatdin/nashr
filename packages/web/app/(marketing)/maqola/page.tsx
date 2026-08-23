// /maqola — the article product page. The revenue product, and the one that is
// not delivered yet: the page says so in the first screen rather than the last.

import type { Metadata } from "next";
import { AssetSlot } from "@/components/marketing/asset-slot";
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
    "Dalil jadvaliga tayangan ilmiy matn: har bir da’vo manbaga bog‘lanadi, iqtiboslar OAK va IEEE talablariga muvofiq rasmiylashtiriladi. Tez kunda.",
};

const STRUCTURES = [
  {
    key: "referat",
    n: "I.",
    title: "Referat",
    body: "Kirish, asosiy qism, xulosa, adabiyotlar ro‘yxati — so‘ralgan hajmda.",
  },
  {
    key: "kurs",
    n: "II.",
    title: "Kurs ishi",
    body: "Mundarija, nazariy bob, amaliy bob, xulosa, adabiyotlar va ilovalar.",
  },
  {
    key: "ilmiy",
    n: "III.",
    title: "Ilmiy maqola",
    body: "Annotatsiya, adabiyotlar sharhi, metodika, natijalar, muhokama, xulosa.",
  },
  {
    key: "hisobot",
    n: "IV.",
    title: "Hisobot",
    body: "Kirish, tahlil, natijalar, tavsiyalar — tekshiriladigan tuzilmada.",
  },
] as const;

export default function ArticlesPage() {
  return (
    <>
      <PageHero
        eyebrow="Maqola"
        title="Ish sizniki — biz tuzilmani beramiz."
        lede="Maqola matni dalil jadvalidan o‘sadi: avval qaysi da’vo qaysi manbaga tayanishi aniqlanadi, keyin bo‘limlar yoziladi. Manbasiz jumla matnga kirmaydi."
      >
        <span className="mkt-chip">Tez kunda</span>
        <ArrowLink href={ROUTES.presentations}>Hozircha taqdimotdan boshlang</ArrowLink>
      </PageHero>

      <Band tight ruled>
        <Claim
          folio="I."
          title="Dalil jadvali — asosiy ob’ekt"
          body={[
            "Maqolaning yadrosi matn emas, dalil jadvali: har bir da’vo, uni tasdiqlovchi manba bo‘lagi va o‘sha bo‘lakdagi aniq iqtibos bitta qatorda turadi.",
            "Bo‘limlar shu jadvaldan yoziladi. Qator bo‘sh bo‘lsa, da’vo matnga chiqmaydi — u savol bo‘lib qoladi.",
          ]}
          visual={
            <AssetSlot
              label="Dalil jadvali: da’vo, manba, iqtibos va holat ustunlari"
              note="Asset: public/marketing/shots/evidence-matrix.png"
              url="nashr.uz/projects/…"
            />
          }
        />

        {/* COPY:FOUNDER — iqtibos intizomi: OAK/GOST va IEEE haqidagi asosiy argument */}
        <FounderCopy>
          <Claim
            folio="II."
            title="Iqtibos intizomi"
            flip
            body={[
              "O‘zbek universitetlari talab qiladigan rasmiylashtirish qoidalari va xalqaro jurnallarning talablari bir xil emas. Nashr ikkalasini ham biladi va bittasini tanlab, oxirigacha unga rioya qiladi.",
              "Bu blok muallif matnini kutmoqda: qaysi uslublar qo‘llab-quvvatlanadi va ular qanday tekshiriladi.",
            ]}
            visual={
              <AssetSlot
                label="Adabiyotlar ro‘yxati: bitta uslubda, matndagi havolalar bilan bog‘langan"
                note="Asset: public/marketing/shots/bibliography.png"
                variant="plate"
              />
            }
          />
        </FounderCopy>
      </Band>

      <Band tone="inset" tight>
        <SectionHead
          folio="III."
          title="To‘rtta akademik tuzilma"
          lede="Har biri o‘z bo‘limlari va o‘z talablari bilan — universitet qabul qiladigan shaklda."
        />
        <CellGrid
          cells={STRUCTURES.map((entry) => ({
            key: entry.key,
            n: entry.n,
            title: entry.title,
            body: entry.body,
          }))}
          columns={2}
        />
      </Band>

      <Band tight>
        <SectionHead folio="IV." title="Hozirgi holat" />
        <div className="mkt-prose">
          <p>
            Maqola dvigateli hali ochilmagan. Biz uni taqdimotlar bilan bir xil qoidada quramiz:
            manbasiz da’vo yo‘q, to‘qilgan adabiyot yo‘q. Ochilganda bu sahifada yozib qo‘yamiz.
          </p>
          <p>
            Shu vaqtgacha taqdimot dvigateli ishlaydi va u ham xuddi shu qoidada ishlaydi —
            mexanizmni o‘sha yerda ko‘rib olsangiz bo‘ladi.
          </p>
        </div>
      </Band>

      <CloseCta
        line="Ish sizniki. Tuzilma bizdan."
        sub="Maqola ochilgunicha taqdimotdan boshlang — dalilga bog‘lash mexanizmi bir xil."
        primaryHref={startHref()}
        primaryLabel="Taqdimotdan boshlash"
        secondaryHref={ROUTES.presentations}
        secondaryLabel="Taqdimot haqida"
      />
    </>
  );
}
