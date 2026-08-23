// /haqida — short, real, and honest about what exists today.

import type { Metadata } from "next";
import { ROUTES, SOCIAL, startHref } from "@/components/marketing/links";
import { Band, CloseCta, FounderCopy, PageHero, SectionHead } from "@/components/marketing/section";

export const metadata: Metadata = {
  title: "Haqida",
  description:
    "Nashr — O‘zbekiston uchun manbaga asoslangan akademik ishlab chiqarish platformasi: da’vo manbaga bog‘lanadi, to‘qima o‘tmaydi.",
};

export default function AboutPage() {
  return (
    <>
      <PageHero
        eyebrow="Haqida"
        title="Nashr — dvigateli bor nashriyot"
        lede="“Nashr” — chop etish degani. Bu mintaqada da’vo manbasiz bilim hisoblanmagan; biz o‘sha talabni dasturga aylantirdik."
      />

      <Band tight ruled>
        {/* COPY:FOUNDER — nima uchun qurilgani: muallif hikoyasi, 2-3 xatboshi */}
        <FounderCopy>
          <div className="mkt-prose">
            <h2>Nega qurildik</h2>
            <p>
              Bu blok muallif matnini kutmoqda: Nashr qanday muammodan tug‘ilgani va kimlar uchun
              qurilgani haqida qisqa, aniq hikoya.
            </p>
            <h2>Nimaga ishonamiz</h2>
            <p>
              Bu blok muallif matnini kutmoqda: manba, mehnat va halollik haqidagi uchta qisqa
              tezis.
            </p>
          </div>
        </FounderCopy>
      </Band>

      <Band tight>
        <SectionHead folio="I." title="Bugungi holat" />
        <div className="mkt-prose">
          <p>
            Taqdimot dvigateli ishlaydi: manba yuklanadi, taqdimot yig‘iladi va HTML, PDF hamda PPTX
            ko‘rinishida yetkaziladi. Maqola dvigateli qurilmoqda.
          </p>
          <p>
            Ishlash tillari: o‘zbek, qoraqalpoq, rus va ingliz. Sayt hozircha faqat o‘zbek tilida —
            boshqa tillar keyin qo‘shiladi.
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
        line="Manbadan boshlanadi."
        primaryHref={startHref()}
        primaryLabel="Boshlash"
        secondaryHref={ROUTES.help}
        secondaryLabel="Yordam"
      />
    </>
  );
}
