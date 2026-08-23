// /maxfiylik — the privacy page. The mechanics below are what the system
// actually does; the legal wording itself is still owed.

import type { Metadata } from "next";
import { SOCIAL } from "@/components/marketing/links";
import { Band, FounderCopy, PageHero } from "@/components/marketing/section";

export const metadata: Metadata = {
  title: "Maxfiylik siyosati",
  description:
    "Nashr qanday ma’lumot to‘playdi, yuklangan hujjatlar qayerda saqlanadi va ular nima uchun ishlatiladi.",
};

export default function PrivacyPage() {
  return (
    <>
      <PageHero eyebrow="Huquqiy" title="Maxfiylik siyosati" />

      <Band tight ruled>
        <div className="mkt-prose">
          <p className="mkt-prose-meta">Holat: matn huquqiy ko‘rikni kutmoqda.</p>

          <h2>Qanday ma’lumot to‘planadi</h2>
          <p>
            Kirish uchun: Telegram hisobingiz identifikatori yoki elektron pochta manzilingiz
            (Google orqali kirsangiz — Google bergan manzil). Ishlash uchun: siz yuklagan hujjatlar,
            yozgan mavzuingiz va tayyor bo‘lgan fayllar. Hisob uchun: to‘lov va yechim yozuvlari.
          </p>

          <h2>Yuklangan hujjatlar</h2>
          <p>
            Hujjatlar yopiq saqlanadi va ularga faqat siz kirasiz. Ular taqdimot yoki maqola
            yaratish uchun ishlatiladi: matn bo‘laklarga ajratiladi, so‘ng da’volarni manbaga
            bog‘lash uchun o‘qiladi. Hujjat mazmuni buyruq sifatida bajarilmaydi — u faqat
            ma’lumot.
          </p>

          <h2>Yuklab olish havolalari</h2>
          <p>
            Tayyor fayllar imzolangan, muddatli havola orqali beriladi: havola yetti kundan keyin
            ishlamaydi. Ulashish havolasini siz o‘zingiz yaratasiz va u faqat o‘sha ishni ko‘rsatadi.
          </p>

          {/* COPY:FOUNDER — huquqiy matn: saqlash muddati, o‘chirish tartibi, uchinchi tomon xizmatlari, aloqa */}
          <FounderCopy>
            <h2>Saqlash muddati va o‘chirish</h2>
            <p>
              Bu blok muallif va yurist matnini kutmoqda: ma’lumot qancha saqlanadi, foydalanuvchi
              qanday o‘chirtiradi va qaysi uchinchi tomon xizmatlari ishtirok etadi.
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
