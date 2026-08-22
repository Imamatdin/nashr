"use client";

import { notFound } from "next/navigation";
import { useState, type ReactNode } from "react";
import {
  ApprovalCard,
  ContextCards,
  FilterTable,
  LoadingState,
  PromptBar,
  SearchList,
  StreamingText,
  TaskRows,
  ThinkingState,
  ToolChips,
  type FilterTableRow,
  type SearchResult,
  type TaskRow,
} from "@/components/bui";

const STEP_LABELS = [
  "Manbalar o‘qilmoqda",
  "Dalillar jamlanmoqda",
  "Talablar hisobga olinmoqda",
  "Dizayn yo‘nalishi tanlanmoqda",
  "Slaydlar ketma-ketligi tuzilmoqda",
  "Vizuallar tayyorlanmoqda",
  "Taqdimot yig‘ilmoqda",
];

const PACKAGES = [
  { key: "presentation_basic", name: "Oddiy", tag: "5 000 so‘m" },
  { key: "presentation_standard", name: "Standart", tag: "10 000 so‘m" },
  { key: "presentation_premium", name: "Premium", tag: "15 000 so‘m" },
];

const LANGUAGES = [
  { key: "uz", name: "O‘zbekcha" },
  { key: "kaa", name: "Qaraqalpaqsha" },
  { key: "ru", name: "Русский" },
  { key: "en", name: "English" },
];

const PROJECTS: SearchResult[] = [
  { key: "p-1", label: "Yoritish davri: aql-idrok asrining tug‘ilishi", meta: "18.08" },
  { key: "p-2", label: "Orol dengizi qurishi: suv balansi va oqibatlar", meta: "17.08" },
  { key: "p-3", label: "Alisher Navoiy g‘azallarida ramziy obrazlar", meta: "15.08" },
  { key: "p-4", label: "Amir Temur davrida savdo yo‘llari", meta: "12.08" },
  { key: "p-5", label: "Zamonaviy fizika: kvant o‘lchovlari", meta: "09.08" },
];

const TABLE_ROWS: FilterTableRow[] = [
  {
    key: "p-1",
    filter: "ready",
    cells: {
      title: "Yoritish davri: aql-idrok asrining tug‘ilishi",
      created: "18.08",
      status: "Tayyor",
      pkg: "Standart",
    },
  },
  {
    key: "p-2",
    filter: "generating",
    cells: {
      title: "Orol dengizi qurishi: suv balansi",
      created: "17.08",
      status: "Yaratilmoqda",
      pkg: "Premium",
    },
  },
  {
    key: "p-3",
    filter: "draft",
    cells: {
      title: "Alisher Navoiy g‘azallarida ramziy obrazlar",
      created: "15.08",
      status: "Qoralama",
      pkg: "Oddiy",
    },
  },
  {
    key: "p-4",
    filter: "ready",
    cells: {
      title: "Amir Temur davrida savdo yo‘llari",
      created: "12.08",
      status: "Tayyor",
      pkg: "Standart",
    },
  },
  {
    key: "p-5",
    filter: "draft",
    cells: {
      title: "Zamonaviy fizika: kvant o‘lchovlari",
      created: "09.08",
      status: "Qoralama",
      pkg: "Oddiy",
    },
  },
];

const STATUS_CLASS: Record<string, string> = {
  ready: "filter-status-done",
  generating: "filter-status-progress",
  draft: "filter-status-todo",
};

function Cell({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <section
      data-cell={n}
      className="flex flex-col gap-3 rounded-card bg-canvas p-5 shadow-hairline"
    >
      <header className="flex items-baseline gap-2">
        <span className="font-mono text-[11px] text-ink-3 tabular-nums">{n}</span>
        <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
      </header>
      <div className="flex min-h-[140px] flex-col items-start justify-start">{children}</div>
    </section>
  );
}

export default function ComponentGalleryPage() {
  if (process.env.NODE_ENV === "production") notFound();

  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<string[]>(["yoritish-davri-tarixi.pdf"]);
  const [pkg, setPkg] = useState("presentation_standard");
  const [language, setLanguage] = useState("uz");
  const [failed, setFailed] = useState(false);
  const [thinkingWorking, setThinkingWorking] = useState(true);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [streamKey, setStreamKey] = useState(0);

  const taskRows: TaskRow[] = STEP_LABELS.map((label, i) => ({
    key: `step-${i}`,
    index: i + 1,
    label,
    meta: `${i + 1}/7`,
    status:
      i < 3 ? "completed" : i === 3 ? (failed ? "failed" : "running") : ("pending" as const),
    details:
      i === 3
        ? [
            { label: "Mavzu ohangi tahlil qilindi", meta: "12 dalil" },
            { label: "Rang palitrasi tanlanmoqda", meta: "60-30-10" },
          ]
        : undefined,
  }));

  const results = query
    ? PROJECTS.filter((p) => p.label.toLowerCase().includes(query.toLowerCase()))
    : PROJECTS.slice(0, 5);

  return (
    <main className="min-h-dvh bg-inset px-6 pt-16 pb-16">
      <div className="mx-auto max-w-[1360px]">
        <h1 className="font-display text-[26px] text-ink">Nashr komponentlari</h1>
        <p className="mt-1 text-[13px] text-ink-2">
          beautifului.dev’dan ko‘chirilgan o‘n komponent, jonli Nashr ma’lumotlari bilan.
        </p>

        <div className="mt-12 grid grid-cols-1 gap-5 lg:grid-cols-2 xl:grid-cols-3">
          <Cell n="#08" title="Prompt bar">
            <PromptBar
              value={draft}
              onChange={setDraft}
              onSend={() => setDraft("")}
              placeholder="Mavzu yoki sarlavhani yozing… @ bilan manba qo‘shing"
              maxLength={200}
              attachments={attachments}
              onAttach={(files) => setAttachments((c) => [...c, ...files.map((f) => f.name)])}
              onRemoveAttachment={(i) => setAttachments((c) => c.filter((_, j) => j !== i))}
              accept=".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv"
              maxAttachments={10}
              sources={[
                {
                  key: "attach",
                  name: "Fayl qo‘shish",
                  desc: "Kompyuteringizdan yuklang",
                  icon: "clip",
                  attach: true,
                },
                {
                  key: "sources",
                  name: "Loyiha manbalari",
                  desc: "2 ta ro‘yxatdan o‘tgan fayl",
                  icon: "layers",
                },
                { key: "web", name: "Akademik qidiruv", desc: "OpenAlex, arXiv", icon: "globe" },
                { key: "stats", name: "Statistika", desc: "Raqamli dalillar", icon: "chart" },
              ]}
              commands={[
                { key: "referat", name: "/referat", desc: "Referat tuzilishi" },
                { key: "kurs", name: "/kurs-ishi", desc: "Kurs ishi tuzilishi" },
                { key: "maqola", name: "/maqola", desc: "Ilmiy maqola" },
              ]}
              onCommand={() => undefined}
              pickers={[
                {
                  key: "package",
                  label: "Paket",
                  value: pkg,
                  options: PACKAGES,
                  onChange: setPkg,
                },
                {
                  key: "language",
                  label: "Til",
                  value: language,
                  options: LANGUAGES,
                  onChange: setLanguage,
                },
              ]}
            />
          </Cell>

          <Cell n="#06" title="Task rows">
            <div className="flex w-full flex-col gap-3">
              <button
                type="button"
                onClick={() => setFailed((v) => !v)}
                className="w-fit rounded-control bg-surface px-2.5 py-1 text-[12px] font-medium text-ink shadow-btn"
              >
                {failed ? "Qayta ishga tushirish" : "Xatolikni ko‘rsatish"}
              </button>
              <TaskRows rows={taskRows} onRetry={() => setFailed(false)} />
            </div>
          </Cell>

          <Cell n="#02" title="Thinking">
            <div className="flex w-full flex-col gap-3">
              <button
                type="button"
                onClick={() => setThinkingWorking((v) => !v)}
                className="w-fit rounded-control bg-surface px-2.5 py-1 text-[12px] font-medium text-ink shadow-btn"
              >
                {thinkingWorking ? "Tugatish" : "Qayta boshlash"}
              </button>
              <ThinkingState
                working={thinkingWorking}
                activeLabel="Dalillar tekshirilmoqda"
                doneLabel="4 soniyada tekshirildi"
                variant="Steps"
                rows={[
                  { primary: "Manbalar o‘qilmoqda", secondary: "2 fayl" },
                  { primary: "Iqtiboslar solishtirilmoqda", secondary: "18 da’vo" },
                  { primary: "Dizayn yo‘nalishi tanlanmoqda" },
                ]}
              />
            </div>
          </Cell>

          <Cell n="#01" title="Loading">
            <div className="flex flex-col gap-4">
              <LoadingState label="Taqdimot yig‘ilmoqda" variant="Drive" />
              <LoadingState label="Manbalar o‘qilmoqda" variant="Dots" />
              <LoadingState label="Vizuallar tayyorlanmoqda" variant="Orbit" />
            </div>
          </Cell>

          <Cell n="#03" title="Streaming">
            <div className="flex w-full flex-col gap-3">
              <button
                type="button"
                onClick={() => setStreamKey((k) => k + 1)}
                className="w-fit rounded-control bg-surface px-2.5 py-1 text-[12px] font-medium text-ink shadow-btn"
              >
                Qayta oqizish
              </button>
              <StreamingText
                key={streamKey}
                text="Yoritish davri XVII–XVIII asrlarda aql-idrokni bilimning asosiy manbasi deb e’lon qildi; Volter va Monteskye davlat tuzilishini qayta o‘ylashga majbur qildi."
                speed={55}
                sources={[
                  { key: "s-1", name: "Yoritish davri tarixi", meta: "PDF · 24-bet" },
                  { key: "s-2", name: "Volter va Monteskye tahlil", meta: "DOCX · 7-bet" },
                ]}
                followUps={[
                  "Monteskye qanday hokimiyat bo‘linishini taklif qildi?",
                  "Bu davr O‘rta Osiyoga qanday ta’sir qildi?",
                ]}
              />
            </div>
          </Cell>

          <Cell n="#04" title="Approval">
            <ApprovalCard
              questions={[
                {
                  q: "Taqdimot kimga mo‘ljallangan?",
                  type: "radio",
                  options: [
                    { label: "Talaba", hint: "Savol-javob va mashqlar bilan" },
                    { label: "O‘qituvchi", hint: "Metodik izohlar bilan" },
                    { label: "Akademik", hint: "Muhokama slaydlari bilan" },
                  ],
                },
                {
                  q: "Qaysi bo‘limlar kerak?",
                  type: "check",
                  options: [
                    { label: "Xronologiya" },
                    { label: "Asosiy shaxslar" },
                    { label: "Manbalar ro‘yxati" },
                  ],
                },
                {
                  q: "Slaydlar soni?",
                  type: "radio",
                  options: [{ label: "5–7" }, { label: "8–12" }, { label: "12–15" }],
                },
              ]}
              summary="Javoblaringiz dalillar jamlanmasini kuchaytiradi."
              allowCustom
              dismissible
              resetLabel="Boshidan"
              onSubmitted={() => undefined}
            />
          </Cell>

          <Cell n="#05" title="Tool chips">
            <ToolChips
              header="4 ta amal, 2 ta xabar"
              rows={[
                {
                  key: "presign",
                  icon: "write",
                  label: "Yuklash",
                  chip: "yoritish-davri-tarixi.pdf",
                  mono: true,
                  state: "done",
                  detail: [{ text: "2.7 MB · R2 ga yozildi" }],
                },
                {
                  key: "register",
                  icon: "file",
                  label: "Ro‘yxat",
                  chip: "volter-va-monteskye-tahlil.docx",
                  mono: true,
                  state: "done",
                  detail: [{ text: "409 KB · manba sifatida qayd etildi" }],
                },
                {
                  key: "parse",
                  icon: "read",
                  label: "Tahlil",
                  chip: "42 ta bo‘lak ajratildi",
                  state: "done",
                  detail: [
                    { text: "PyMuPDF · 24 bet", tone: "add" },
                    { text: "python-docx · 7 bet", tone: "add" },
                  ],
                },
                {
                  key: "enqueue",
                  icon: "run",
                  label: "Navbat",
                  chip: "job-stub",
                  mono: true,
                  state: "pending",
                  detail: [{ text: "Navbatda kutilmoqda" }],
                },
              ]}
              diffs={[
                {
                  file: "yoritish-davri-tarixi.pdf",
                  add: 24,
                  del: 0,
                  lines: [
                    { text: "24 bet o‘qildi", tone: "add" },
                    { text: "18 da’vo ajratildi", tone: "add" },
                  ],
                },
                {
                  file: "volter-va-monteskye-tahlil.docx",
                  add: 7,
                  del: 2,
                  lines: [
                    { text: "7 bet o‘qildi", tone: "add" },
                    { text: "2 bo‘lak takrorlangan", tone: "del" },
                  ],
                },
              ]}
            />
          </Cell>

          <Cell n="#10" title="Context cards">
            <ContextCards
              title="Barcha bo‘laklar"
              count={42}
              chunks={[
                {
                  key: "c-1",
                  title: "Aql-idrok ta’rifi",
                  meta: "290 belgi",
                  body: "Yoritish davri mutafakkirlari bilimning yagona ishonchli manbasi aql-idrok ekanini e’lon qildilar.",
                  source: "yoritish-davri-tarixi.pdf",
                  badge: "PDF",
                  tone: "red",
                  index: 12,
                },
                {
                  key: "c-2",
                  title: "Hokimiyat bo‘linishi",
                  meta: "1 250 belgi",
                  body: "Monteskye qonun chiqaruvchi, ijro etuvchi va sud hokimiyatini ajratishni taklif qildi.",
                  source: "volter-va-monteskye-tahlil.docx",
                  badge: "DOC",
                  tone: "accent",
                  index: 27,
                },
              ]}
            />
          </Cell>

          <Cell n="#15" title="Search">
            <SearchList
              query={query}
              onQueryChange={setQuery}
              placeholder="Loyihalarni qidirish…"
              results={results}
              onPick={(item) => setQuery(item.label)}
              emptyTitle="Hech narsa topilmadi"
              emptyHint="Boshqa so‘z bilan qidirib ko‘ring"
            />
          </Cell>

          <Cell n="#13" title="Filter table">
            <FilterTable
              filters={[
                { key: "all", label: "Hammasi", count: 5 },
                { key: "draft", label: "Qoralama", dot: "var(--orange)", count: 2 },
                { key: "generating", label: "Yaratilmoqda", dot: "var(--accent)", count: 1 },
                { key: "ready", label: "Tayyor", dot: "var(--green)", count: 2 },
              ]}
              active={filter}
              onChange={setFilter}
              columns={[
                { key: "title", label: "Loyiha", width: "1.6fr" },
                { key: "created", label: "Sana", width: "0.5fr" },
                { key: "status", label: "Holat", width: "0.9fr" },
                { key: "pkg", label: "Paket", width: "0.7fr" },
              ]}
              rows={TABLE_ROWS}
              renderCell={(row, column) => {
                if (column.key === "status") {
                  return (
                    <span
                      className={`inline-flex h-5 items-center rounded-[5px] px-1.5 text-[11px] font-medium ${STATUS_CLASS[row.filter]}`}
                    >
                      {row.cells.status}
                    </span>
                  );
                }
                if (column.key === "title") {
                  return <span className="font-medium text-ink">{row.cells.title}</span>;
                }
                if (column.key === "created") {
                  return <span className="tabular-nums">{row.cells.created}</span>;
                }
                return row.cells[column.key];
              }}
            />
          </Cell>
        </div>
      </div>
    </main>
  );
}
