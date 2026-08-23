// /haqida — short, real, and honest about what exists today.

import type { Metadata } from "next";
import { ROUTES, SOCIAL, startHref } from "@/components/marketing/links";
import { Band, CloseCta, FounderCopy, PageHero, SectionHead } from "@/components/marketing/section";

export const metadata: Metadata = {
  title: "Haqida",
  description:
    "Nashr O‘zbekiston uchun manbaga asoslangan akademik ishlab chiqarish platformasi. Da’vo manbaga bog‘lanadi, to‘qima o‘tmaydi.",
};

export default function AboutPage() {
  return (
    <>
      <PageHero
        title="Dvigateli bor nashriyot"
        lede="“Nashr” chop etish degani. Bu mintaqada manbasiz da’vo bilim hisoblanmagan, biz o‘sha talabni dasturga aylantirdik."
      />

      <Band tight ruled>
        {/* COPY:FOUNDER — nima uchun qurilgani: muallif hikoyasi, 2-3 xatboshi */}
        <FounderCopy>
          <div className="mkt-prose">
            <h2>Nega qurildik</h2>
            <p>
              Bu blok muallif matnini kutmoqda: Nashr qanday muammodan tug‘ilgani va kim uchun
              qurilgani.
            </p>
            <h2>Nimaga ishonamiz</h2>
            <p>Bu blok muallif matnini kutmoqda: manba, mehnat va halollik haqida uchta tezis.</p>
          </div>
        </FounderCopy>
      </Band>

      <Band tight>
        <SectionHead title="Bugungi holat" />
        <div className="mkt-prose">
          <p>
            Taqdimot dvigateli ishlaydi: manba yuklanadi, taqdimot yig‘iladi va HTML, PDF hamda
            PPTX ko‘rinishida yetkaziladi. Maqola dvigateli qurilmoqda.
          </p>
          <p>
            Ishlash tillari: o‘zbek, qoraqalpoq, rus va ingliz. Sayt hozircha faqat o‘zbek
            tilida, qolgan tillar keyin qo‘shiladi.
          </p>
          <p>
            Savol yoki taklif bo‘lsa,{" "}
            <a href={SOCIAL.telegram} target="_blank" rel="noreferrer">
              Telegram
            </a>{" "}
            orqali yozing.
          </p>
        </div>
      </Band>

      <CloseCta
        line="Ish manbadan boshlanadi."
        primaryHref={startHref()}
        primaryLabel="Boshlash"
        secondaryHref={ROUTES.help}
        secondaryLabel="Yordam"
      />
    </>
  );
}
