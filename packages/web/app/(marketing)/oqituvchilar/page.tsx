// /oqituvchilar — the integrity page. Problem, difference, what a teacher can
// actually see, and an invitation to run a pilot. The argument prose belongs to
// the founder; the mechanism claims are the ones the engine can back.

import type { Metadata } from "next";
import { AssetSlot } from "@/components/marketing/asset-slot";
import { ROUTES, SOCIAL } from "@/components/marketing/links";
import {
  Band,
  CellGrid,
  Claim,
  CloseCta,
  FounderCopy,
  PageHero,
  SectionHead,
} from "@/components/marketing/section";

export const metadata: Metadata = {
  title: "O‘qituvchilarga",
  description:
    "Nashr ishni talaba o‘rniga o‘ylab bermaydi: har bir da’vo talaba yuklagan manbaga bog‘lanadi va tekshirish uchun ochiq turadi.",
};

const VISIBLE = [
  {
    key: "provenance",
    n: "I.",
    title: "Qaysi gap qayerdan",
    body: "Har bir da’vo yonida manba fayli, bo‘lak raqami va iqtibos turadi. Tasodifiy tekshiruv bir necha soniya oladi.",
  },
  {
    key: "sources",
    n: "II.",
    title: "Qanday manbalar",
    body: "Ish qaysi hujjatlarga tayanganini ko‘rasiz: fayl nomi, hajmi va yuklangan vaqti.",
  },
  {
    key: "share",
    n: "III.",
    title: "Ulashish havolasi",
    body: "Talaba ishni havola bilan yuboradi — yuklab olmasdan, brauzerda ochib ko‘rasiz.",
  },
] as const;

export default function TeachersPage() {
  return (
    <>
      <PageHero
        eyebrow="O‘qituvchilarga"
        title="Manbasiz da’vo bu yerda ham o‘tmaydi"
        lede="Nashr talabaning o‘rniga o‘ylamaydi. U talaba bergan manbadan chiqmaydigan hech narsa yozmaydi va nimaga tayanganini yashirmaydi."
      />

      <Band tight ruled>
        {/* COPY:FOUNDER — muammo: referat bozori, to‘qilgan adabiyotlar, tekshirish yuki */}
        <FounderCopy>
          <SectionHead
            folio="I."
            title="Muammo — matn emas, tekshirib bo‘lmasligi"
            lede="Bu blok muallif matnini kutmoqda: tayyor referat bozori, to‘qilgan adabiyotlar ro‘yxati va o‘qituvchi zimmasiga tushgan tekshirish yuki haqida qisqa, aniq argument."
          />
        </FounderCopy>
      </Band>

      <Band tight>
        {/* COPY:FOUNDER — farq: Nashr nima qiladi va nima qilmaydi */}
        <FounderCopy>
          <Claim
            folio="II."
            title="Nashr nimasi bilan farq qiladi"
            body={[
              "Dvigatel faqat yuklangan hujjatlardan foydalanadi. Ichki tekshiruvchi manbada yo‘q raqamni yoki mavjud bo‘lmagan adabiyotni topsa, bo‘limni qaytaradi.",
              "Bu blok muallif matnini kutmoqda: mehnat talabaniki bo‘lib qolishi haqidagi asosiy argument.",
            ]}
            visual={
              <AssetSlot
                label="Provenans: da’vo, iqtibos va manba fayli bitta qatorda"
                note="Asset: public/marketing/shots/provenance.png"
                url="nashr.uz/p/…"
              />
            }
          />
        </FounderCopy>
      </Band>

      <Band tone="inset" tight>
        <SectionHead
          folio="III."
          title="Siz nimani ko‘rasiz"
          lede="Talabadan qo‘shimcha hujjat so‘ramasdan, ishning o‘zidan."
        />
        <CellGrid
          cells={VISIBLE.map((entry) => ({
            key: entry.key,
            n: entry.n,
            title: entry.title,
            body: entry.body,
          }))}
        />
      </Band>

      <Band tight>
        {/* COPY:FOUNDER — pilot taklifi: kafedra bilan qanday boshlanadi */}
        <FounderCopy>
          <SectionHead
            folio="IV."
            title="Kafedra bilan sinov"
            lede="Bu blok muallif matnini kutmoqda: pilot qanday boshlanadi, kim ishtirok etadi va natija qanday baholanadi."
          />
        </FounderCopy>
      </Band>

      <CloseCta
        line="Tekshirish oson bo‘lsin."
        sub="Kafedrangiz bilan sinovdan o‘tkazmoqchi bo‘lsangiz, yozing — birga rejalashtiramiz."
        primaryHref={SOCIAL.telegram}
        primaryLabel="Telegramda yozish"
        secondaryHref={ROUTES.about}
        secondaryLabel="Nashr haqida"
      />
    </>
  );
}
