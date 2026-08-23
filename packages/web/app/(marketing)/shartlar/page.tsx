// /shartlar — terms of use. Same rule as the privacy page: the mechanics are
// what the system does, the legal wording is owed.

import type { Metadata } from "next";
import { ROUTES, SOCIAL } from "@/components/marketing/links";
import { Band, FounderCopy, PageHero } from "@/components/marketing/section";

export const metadata: Metadata = {
  title: "Foydalanish shartlari",
  description:
    "Nashrdan foydalanish qoidalari: hisob, to‘lov va qaytarish, natijaga egalik va akademik javobgarlik.",
};

export default function TermsPage() {
  return (
    <>
      <PageHero title="Foydalanish shartlari" />

      <Band tight ruled>
        <div className="mkt-prose">
          <p className="mkt-prose-meta">Holat: matn huquqiy ko‘rikni kutmoqda.</p>

          <h2>Hisob</h2>
          <p>
            Hisobga Telegram, Google yoki elektron pochtaga yuborilgan havola orqali kirasiz.
            Hisobingizdagi ish va mablag‘ sizniki; uni boshqalarga uzatish ko‘zda tutilmagan.
          </p>

          <h2>To‘lov va qaytarish</h2>
          <p>
            Har bir buyurtma hisobingizdagi mablag‘dan yechiladi. Ish xatolik bilan tugasa, mablag‘
            qaytariladi. Paket narxlari va tarkibi{" "}
            <a href={ROUTES.pricing} className="mkt-navlink">
              narxlar sahifasida
            </a>{" "}
            ko‘rsatilgan.
          </p>

          <h2>Natijaga egalik</h2>
          <p>
            Siz yuklagan hujjatlar sizniki bo‘lib qoladi. Tayyor bo‘lgan taqdimot va matn ham
            sizniki: undan o‘qishda, ishda va nashrda foydalanishingiz mumkin.
          </p>

          <h2>Akademik javobgarlik</h2>
          <p>
            Nashr manbaga bog‘lanmagan da’vo chiqarmaslikka qurilgan, lekin topshirilayotgan ish
            uchun javobgarlik sizda. O‘quv muassasangiz qoidalariga rioya qilish ham sizning
            zimmangizda.
          </p>

          {/* COPY:FOUNDER — huquqiy matn: xizmat kafolatlari chegarasi, taqiqlangan foydalanish, shartlar o‘zgarishi */}
          <FounderCopy>
            <h2>Xizmat chegaralari</h2>
            <p>
              Bu blok muallif va yurist matnini kutmoqda: kafolatlar chegarasi, taqiqlangan
              foydalanish holatlari va shartlar qanday o‘zgarishi.
            </p>
          </FounderCopy>

          <h2>Aloqa</h2>
          <p>
            Savollar uchun:{" "}
            <a href={SOCIAL.telegram} target="_blank" rel="noreferrer">
              Telegram
            </a>
            .
          </p>
        </div>
      </Band>
    </>
  );
}
