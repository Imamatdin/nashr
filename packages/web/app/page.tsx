// Landing — gate (b): the full argument. The page scrolls and argues
// (steal/reject note 10): stakes, mechanism, proof, lineage, use, ask.
// Folio-numbered sections; every artifact framed as a plate with a mono
// caption. Two gold moments only — the hero CTA and the closing CTA, and
// they are five viewports apart.

import Image from "next/image";
import Link from "next/link";
import { DitherPlate, GildOnView, InkLine, InkReveal, TiltPlate } from "@/components/motion";
import plates from "@/public/plates/manifest.json";

const decks = {
  integration: {
    src: "/decks/sco2-integration.jpg",
    width: 1467,
    height: 825,
    alt: "Nashr dvigateli chiqargan slayd: sarlavha, izohli xatboshi va markazda chip–rack–inshoot halqalarini ko’rsatuvchi doiraviy sxema",
    caption: "LAVHA III — SLAYD 11 · SXEMA",
  },
  criticalPoint: {
    src: "/decks/sco2-critical-point.jpg",
    width: 1467,
    height: 825,
    alt: "Nashr dvigateli chiqargan slayd: 31°C va 73.8 bar chegarasi haqidagi sarlavha, to’rtta dalil bandi va CO₂ ning faza diagrammasi",
    caption: "LAVHA IV — SLAYD 07 · MA’LUMOT",
  },
} as const;

export default function LandingPage() {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="container topbar-inner">
          <span className="wordmark">Nashr</span>
          <nav className="nav-links">
            <Link href="/login">Kirish</Link>
          </nav>
        </div>
      </header>

      <main className="page">
        <div className="container">
          {/* ------------------------------------------------ I. stakes */}
          <section className="grid items-center gap-14 py-8 md:grid-cols-[1.1fr_0.9fr] md:py-14">
            {/* Section I animates via the CSS state (.ink-css), not framer:
                the first viewport must paint before hydration. */}
            <div>
              <div className="ink-css">
                <p className="folio">I.</p>
              </div>
              <div className="ink-css-lcp" style={{ marginTop: "1rem", animationDelay: "80ms" }}>
                <h1
                  className="font-display"
                  style={{ fontSize: "var(--text-hero)", maxWidth: "20ch", textWrap: "balance" }}
                >
                  Ma&rsquo;ruzangiz savolga{" "}
                  <em className="not-italic" style={{ color: "var(--zangori)" }}>
                    dosh beradimi?
                  </em>
                  <span className="cite-mark" style={{ fontSize: "0.3em" }}>
                    1
                  </span>
                </h1>
              </div>
              <div className="ink-css" style={{ marginTop: "1.6rem", animationDelay: "160ms" }}>
                <p className="max-w-[44ch] text-xl" style={{ color: "var(--ink-88)" }}>
                  Nashr har bir fikrni manbaga bog&rsquo;laydi. Ustoz so&rsquo;raganda —
                  javob tayyor.
                </p>
              </div>
              <div className="ink-css" style={{ marginTop: "2.2rem", animationDelay: "240ms" }}>
                <div className="flex flex-wrap items-center gap-6">
                  <GildOnView>
                    <span className="gild-underline inline-block">
                      <Link
                        href="/login"
                        className="inline-flex items-center px-7 py-3.5 font-semibold"
                        style={{
                          background: "var(--zangori)",
                          color: "var(--qogoz)",
                          borderRadius: "var(--radius)",
                        }}
                      >
                        Boshlash
                      </Link>
                    </span>
                  </GildOnView>
                  <Link href="/login" className="font-semibold">
                    A&rsquo;zo bo&rsquo;lganmisiz? Kirish
                  </Link>
                </div>
              </div>
              <div className="ink-css" style={{ marginTop: "3.4rem", animationDelay: "320ms" }}>
                <hr className="footnote" />
                <p className="footnote-text">
                  <span className="cite-mark" style={{ verticalAlign: "baseline" }}>
                    1
                  </span>{" "}
                  Har bir slayd o&rsquo;z manbasiga havola qiladi — bu odob emas,
                  dastur darajasidagi talab. Manbasiz da&rsquo;vo Nashr uchun
                  bilim emas.
                </p>
              </div>
            </div>

            <div className="ink-css" style={{ animationDelay: "250ms" }}>
              <TiltPlate>
                <figure className="plate m-0">
                  <DitherPlate
                    src={plates["hero-observatory"].full}
                    dither={plates["hero-observatory"].dither}
                    alt={plates["hero-observatory"].alt}
                    width={plates["hero-observatory"].width}
                    height={plates["hero-observatory"].height}
                    sizes="(max-width: 768px) 92vw, 44vw"
                    priority
                    immediate
                  />
                  <figcaption className="plate-caption">
                    LAVHA I — {plates["hero-observatory"].title}
                  </figcaption>
                </figure>
              </TiltPlate>
            </div>
          </section>

          <hr className="folio-rule" style={{ marginTop: "5rem" }} />

          {/* -------------------------------------------- II. mechanism */}
          <section className="grid items-start gap-14 py-20 md:grid-cols-[0.78fr_1.22fr] md:gap-20">
            <InkReveal>
              <InkLine>
                <figure className="plate m-0">
                  <DitherPlate
                    src={plates["plate-manuscript"].full}
                    dither={plates["plate-manuscript"].dither}
                    alt={plates["plate-manuscript"].alt}
                    width={plates["plate-manuscript"].width}
                    height={plates["plate-manuscript"].height}
                    sizes="(max-width: 768px) 76vw, 32vw"
                  />
                  <figcaption className="plate-caption">
                    LAVHA II — {plates["plate-manuscript"].title}
                  </figcaption>
                </figure>
              </InkLine>
              <InkLine style={{ marginTop: "2rem" }}>
                <aside className="marginalia">
                  Foydalanuvchi matni dalil emas. Faqat yuklangan fayl va undan
                  ajratilgan bo&rsquo;laklar dalil sanaladi — bu qoida dvigatelning
                  o&rsquo;zida yozilgan.
                </aside>
              </InkLine>
            </InkReveal>

            <InkReveal delay={0.1}>
              <InkLine>
                <p className="folio">II.</p>
              </InkLine>
              <InkLine style={{ marginTop: "0.7rem" }}>
                <p className="kicker">Mexanizm</p>
              </InkLine>
              <InkLine style={{ marginTop: "1rem" }}>
                <h2
                  className="font-display"
                  style={{ fontSize: "var(--text-display)", maxWidth: "18ch" }}
                >
                  Nashr matn yozmaydi. U bosma qiladi.
                </h2>
              </InkLine>
              <InkLine style={{ marginTop: "1.3rem" }}>
                <p className="max-w-[52ch] text-lg" style={{ color: "var(--ink-88)" }}>
                  Bosmaxonada sahifa terilishidan oldin manbaga solishtiriladi.
                  Nashrda ham tartib shu: avval dalil yig&rsquo;iladi, keyin gap
                  tuziladi. Teskarisi hech qachon emas.
                </p>
              </InkLine>

              <InkLine style={{ marginTop: "2.6rem" }}>
                <h3 className="font-display text-2xl">
                  Da&rsquo;vo manbaga bog&rsquo;lanadi
                  <span className="cite-mark">2</span>
                </h3>
                <p className="mt-2 max-w-[54ch]" style={{ color: "var(--ink-88)" }}>
                  Slaydga chiqqan har bir raqam, ta&rsquo;rif va iqtibos siz
                  yuklagan hujjatning aniq bo&rsquo;lagidan keladi. Bog&rsquo;lanmagan
                  gap chiqishga yetib bormaydi.
                </p>
              </InkLine>
              <InkLine style={{ marginTop: "1.8rem" }}>
                <h3 className="font-display text-2xl">
                  Tanqidchi rad etadi
                  <span className="cite-mark">3</span>
                </h3>
                <p className="mt-2 max-w-[54ch]" style={{ color: "var(--ink-88)" }}>
                  Ichki tekshiruvchi manbada yo&rsquo;q raqamni yoki mavjud
                  bo&rsquo;lmagan adabiyotni topsa, uni o&rsquo;tkazmaydi —
                  bo&rsquo;limni qaytaradi va qayta yozdiradi.
                </p>
              </InkLine>
              <InkLine style={{ marginTop: "1.8rem" }}>
                <h3 className="font-display text-2xl">
                  Manba — bezak emas
                  <span className="cite-mark">4</span>
                </h3>
                <p className="mt-2 max-w-[54ch]" style={{ color: "var(--ink-88)" }}>
                  Har bir slayd o&rsquo;z manbasini yonida olib yuradi. Ustoz
                  so&rsquo;raganda ochib ko&rsquo;rsatasiz; qayta izlab
                  o&rsquo;tirmaysiz.
                </p>
              </InkLine>

              <InkLine style={{ marginTop: "3rem" }}>
                <hr className="footnote" />
                <p className="footnote-text">
                  <span className="cite-mark" style={{ verticalAlign: "baseline" }}>
                    2
                  </span>{" "}
                  Bog&rsquo;lanish bo&rsquo;lak darajasida: butun fayl emas, aynan
                  o&rsquo;sha xatboshi.
                </p>
                <p className="footnote-text mt-2">
                  <span className="cite-mark" style={{ verticalAlign: "baseline" }}>
                    3
                  </span>{" "}
                  Tekshiruv chiqishdan oldin bo&rsquo;ladi, keyin emas.
                </p>
                <p className="footnote-text mt-2">
                  <span className="cite-mark" style={{ verticalAlign: "baseline" }}>
                    4
                  </span>{" "}
                  Adabiyotlar ro&rsquo;yxati alohida tuzilmaydi — u matndan
                  o&rsquo;sib chiqadi.
                </p>
              </InkLine>
            </InkReveal>
          </section>

          <hr className="folio-rule" />

          {/* ---------------------------------------------- III. artifact */}
          <section className="py-20">
            <InkReveal>
              <InkLine>
                <p className="folio">III.</p>
              </InkLine>
              <InkLine style={{ marginTop: "0.7rem" }}>
                <p className="kicker">Artefakt</p>
              </InkLine>
              <InkLine style={{ marginTop: "1rem" }}>
                <h2
                  className="font-display"
                  style={{ fontSize: "var(--text-display)", maxWidth: "22ch" }}
                >
                  Quyidagilar — dvigatelning haqiqiy chiqishi.
                </h2>
              </InkLine>
              <InkLine style={{ marginTop: "1.3rem" }}>
                <p className="max-w-[58ch] text-lg" style={{ color: "var(--ink-88)" }}>
                  Bu ikki lavha ko&rsquo;rgazma uchun chizilmagan. Ular bitta
                  buyurtmadan chiqqan taqdimotning ikki varag&rsquo;i, qo&rsquo;l
                  tegmagan holida. Taqdimot tili manbadan keladi — bu yerda
                  manbalar ingliz tilida edi.
                </p>
              </InkLine>
            </InkReveal>

            <div className="mt-12 grid gap-10 md:grid-cols-2">
              {[decks.integration, decks.criticalPoint].map((deck, index) => (
                <InkReveal key={deck.src} delay={index * 0.12}>
                  <InkLine>
                    <TiltPlate>
                      {/* Real artifacts, not generated plates: no dither variant
                          exists for them and none should be faked. */}
                      <figure className="plate m-0">
                        <Image
                          src={deck.src}
                          alt={deck.alt}
                          width={deck.width}
                          height={deck.height}
                          sizes="(max-width: 768px) 92vw, 46vw"
                          style={{ width: "100%", height: "auto", display: "block" }}
                        />
                        <figcaption className="plate-caption">{deck.caption}</figcaption>
                      </figure>
                    </TiltPlate>
                  </InkLine>
                </InkReveal>
              ))}
            </div>
          </section>

          <hr className="folio-rule" />

          {/* ----------------------------------------------- IV. heritage */}
          <section className="grid items-center gap-14 py-20 md:grid-cols-[1.15fr_0.85fr] md:gap-20">
            <InkReveal>
              <InkLine>
                <p className="folio">IV.</p>
              </InkLine>
              <InkLine style={{ marginTop: "0.7rem" }}>
                <p className="kicker">Meros</p>
              </InkLine>
              <InkLine style={{ marginTop: "1rem" }}>
                <h2
                  className="font-display"
                  style={{ fontSize: "var(--text-display)", maxWidth: "20ch" }}
                >
                  Bu yerda manbasiz da&rsquo;vo hech qachon bilim sanalmagan.
                </h2>
              </InkLine>
              <InkLine style={{ marginTop: "1.6rem" }}>
                <p className="dropcap max-w-[56ch] text-lg" style={{ color: "var(--ink-88)" }}>
                  Ulug&rsquo;bek rasadxonasida yulduzlar jadvali bir kishining
                  so&rsquo;ziga emas, o&rsquo;lchovga tayangan. Al-Xorazmiy natijani
                  emas, usulni yozib qoldirdi — boshqalar tekshira olsin deb.
                  Beruniy o&rsquo;zi o&rsquo;qimagan kitob haqida yozmadi. Bu
                  madaniyatda havola odob qoidasi emas, isbotning bir qismi edi.
                </p>
              </InkLine>
              <InkLine style={{ marginTop: "1.4rem" }}>
                <p className="max-w-[56ch] text-lg" style={{ color: "var(--ink-88)" }}>
                  Nashr o&rsquo;sha me&rsquo;yorni dasturga aylantiradi.
                  O&rsquo;zgargani — asbob; talab o&rsquo;sha-o&rsquo;sha.
                </p>
              </InkLine>
            </InkReveal>

            <InkReveal delay={0.15}>
              <InkLine>
                <figure className="plate m-0">
                  <DitherPlate
                    src={plates["plate-registan"].full}
                    dither={plates["plate-registan"].dither}
                    alt={plates["plate-registan"].alt}
                    width={plates["plate-registan"].width}
                    height={plates["plate-registan"].height}
                    sizes="(max-width: 768px) 84vw, 34vw"
                  />
                  <figcaption className="plate-caption">
                    LAVHA V — {plates["plate-registan"].title}
                  </figcaption>
                </figure>
              </InkLine>
            </InkReveal>
          </section>

          <hr className="folio-rule" />

          {/* ----------------------------------------------- V. workflow */}
          <section className="py-20">
            <InkReveal>
              <InkLine>
                <p className="folio">V.</p>
              </InkLine>
              <InkLine style={{ marginTop: "0.7rem" }}>
                <p className="kicker">Ish tartibi</p>
              </InkLine>
              <InkLine style={{ marginTop: "1rem" }}>
                <h2
                  className="font-display"
                  style={{ fontSize: "var(--text-display)", maxWidth: "18ch" }}
                >
                  Uch qadam. Ortiqchasi yo&rsquo;q.
                </h2>
              </InkLine>
            </InkReveal>

            <div className="mt-14 grid gap-12 md:grid-cols-3 md:gap-14">
              <InkReveal>
                <InkLine>
                  <p className="folio">1</p>
                  <h3 className="mt-3 font-display text-2xl">Telegramda boshlaysiz</h3>
                  <p className="mt-3 max-w-[36ch]" style={{ color: "var(--ink-88)" }}>
                    Botga mavzuni yozasiz yoki hujjatni tashlaysiz: PDF, DOCX,
                    PPTX. Fayl avval tekshiruvdan o&rsquo;tadi — nima yuklanganini
                    tizim o&rsquo;zi aniqlaydi.
                  </p>
                </InkLine>
              </InkReveal>
              <InkReveal delay={0.1}>
                <InkLine>
                  <p className="folio">2</p>
                  <h3 className="mt-3 font-display text-2xl">Ish stolida kuzatasiz</h3>
                  <p className="mt-3 max-w-[36ch]" style={{ color: "var(--ink-88)" }}>
                    Brauzerdagi ish stolida manbalar, ajratilgan bo&rsquo;laklar va
                    tayyor bo&rsquo;layotgan slaydlar ko&rsquo;rinadi. Qaysi gap
                    qaysi manbadan kelgani ochiq turadi.
                  </p>
                </InkLine>
              </InkReveal>
              <InkReveal delay={0.2}>
                <InkLine>
                  <p className="folio">3</p>
                  <h3 className="mt-3 font-display text-2xl">Uch formatda olasiz</h3>
                  <p className="mt-3 max-w-[36ch]" style={{ color: "var(--ink-88)" }}>
                    HTML interaktiv — brauzerda ochiladi va savollar ishlaydi. PDF —
                    chop etishga. PPTX — PowerPointda. Uchalasi ham asosiy; biri
                    ikkinchisining o&rsquo;rnini bosuvchi emas.
                  </p>
                </InkLine>
              </InkReveal>
            </div>

            <InkReveal delay={0.25}>
              <InkLine style={{ marginTop: "3.4rem" }}>
                <hr className="footnote" />
                <p className="footnote-text">
                  3 eksport formati. Boshqa raqamni va&rsquo;da qilmaymiz — sanab
                  bo&rsquo;lmaydigan narsani sanamaymiz.
                </p>
              </InkLine>
            </InkReveal>
          </section>

          <hr className="folio-rule" />

          {/* ------------------------------------------------ VI. the ask */}
          <section className="flex flex-col items-center py-24 text-center">
            <InkReveal>
              <InkLine>
                <figure className="plate m-0 mx-auto" style={{ maxWidth: "190px" }}>
                  <DitherPlate
                    src={plates["plate-astrolabe"].full}
                    dither={plates["plate-astrolabe"].dither}
                    alt={plates["plate-astrolabe"].alt}
                    width={plates["plate-astrolabe"].width}
                    height={plates["plate-astrolabe"].height}
                    sizes="190px"
                  />
                  <figcaption className="plate-caption">
                    LAVHA VI — {plates["plate-astrolabe"].title}
                  </figcaption>
                </figure>
              </InkLine>
              <InkLine style={{ marginTop: "2.6rem" }}>
                <p className="folio">VI.</p>
              </InkLine>
              <InkLine style={{ marginTop: "1rem" }}>
                <h2
                  className="mx-auto font-display"
                  style={{
                    fontSize: "var(--text-display)",
                    maxWidth: "20ch",
                    textWrap: "balance",
                  }}
                >
                  Savol baribir beriladi. Javob tayyor bo&rsquo;lsin.
                </h2>
              </InkLine>
              <InkLine style={{ marginTop: "2.4rem" }}>
                <div className="flex justify-center">
                  <GildOnView>
                    <span className="gild-underline inline-block">
                      <Link
                        href="/login"
                        className="inline-flex items-center px-7 py-3.5 font-semibold"
                        style={{
                          background: "var(--zangori)",
                          color: "var(--qogoz)",
                          borderRadius: "var(--radius)",
                        }}
                      >
                        Boshlash
                      </Link>
                    </span>
                  </GildOnView>
                </div>
              </InkLine>
              <InkLine style={{ marginTop: "1.8rem" }}>
                <p className="text-sm" style={{ color: "var(--ink-60)" }}>
                  Telegram orqali ham, brauzerda ham.
                </p>
              </InkLine>
            </InkReveal>
          </section>
        </div>
      </main>

      <footer className="footer">
        <div className="container footer-inner">
          <span>© {new Date().getFullYear()} Nashr</span>
          <span>Manbaga asoslangan akademik nashriyot</span>
        </div>
      </footer>
    </div>
  );
}
