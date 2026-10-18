"use client";

import { useState } from "react";
import { ExternalLink, Search } from "lucide-react";
import { searchResearch, type ResearchView } from "@/lib/api";
import { lexUzSearchUrl } from "@/lib/legal-search";
import { useAppSession } from "@/lib/use-session";
import { useLocale } from "./locale-provider";
import "./research-panel.css";

const COPY = {
  en: {
    title: "Find research",
    placeholder: "Search a topic, question, or paper title",
    search: "Search",
    busy: "Searching sources…",
    note: "Results are source records, not verified support for your claims. Read the paper before citing it.",
    legal:
      "Open the same title query in the official Lex.uz database. Nashr does not copy or verify its results.",
    legalLink: "Search Lex.uz",
    open: "Open source",
    empty: "No papers found. Try a more specific query.",
    error: "Search could not finish. Try again.",
    partial: "Some providers were unavailable:",
    abstract: "Abstract",
    download: "Open PDF",
  },
  ru: {
    title: "Найти исследования",
    placeholder: "Тема, вопрос или название статьи",
    search: "Искать",
    busy: "Поиск источников…",
    note: "Результат поиска — запись об источнике, а не подтверждение утверждения. Прочитайте статью перед цитированием.",
    legal:
      "Откройте тот же запрос по названию в официальной базе Lex.uz. Nashr не копирует и не проверяет её результаты.",
    legalLink: "Искать в Lex.uz",
    open: "Открыть источник",
    empty: "Статьи не найдены. Уточните запрос.",
    error: "Не удалось завершить поиск. Попробуйте ещё раз.",
    partial: "Некоторые базы недоступны:",
    abstract: "Аннотация",
    download: "Открыть PDF",
  },
  uz: {
    title: "Tadqiqot izlash",
    placeholder: "Mavzu, savol yoki maqola nomi",
    search: "Qidirish",
    busy: "Manbalar qidirilmoqda…",
    note: "Natijalar — manba yozuvlari, da’voning tasdig‘i emas. Iqtibos keltirishdan oldin maqolani o‘qing.",
    legal:
      "Shu nom so‘rovini Lex.uz rasmiy bazasida oching. Nashr uning natijalarini ko‘chirmaydi yoki tekshirmaydi.",
    legalLink: "Lex.uz’da izlash",
    open: "Manbani ochish",
    empty: "Maqola topilmadi. Aniqroq so‘rov kiriting.",
    error: "Qidiruv tugamadi. Qayta urinib ko‘ring.",
    partial: "Ba’zi bazalar ishlamadi:",
    abstract: "Annotatsiya",
    download: "PDF ni ochish",
  },
  kaa: {
    title: "Izertlew izlew",
    placeholder: "Tema, soraw yamasa maqala atı",
    search: "Izlew",
    busy: "Derekler izlenbekte…",
    note: "Nátiyjeler — derek jazbaları, da'wanıń tastıyıǵı emes. Iqtibos keltiriwden aldın maqalanı oqıń.",
    legal:
      "Usı attaǵı sorawdı Lex.uz rásmiy bazasında ashıń. Nashr onıń nátiyjelerin kóshirmeydi yamasa teksermeydi.",
    legalLink: "Lex.uz'da izlew",
    open: "Derekti ashıw",
    empty: "Maqala tabılmadı. Anıǵıraq soraw kirgiziń.",
    error: "Izlew tamamlanbadı. Qayta urınıp kóriń.",
    partial: "Ba'zi bazalar islemedi:",
    abstract: "Annotaciya",
    download: "PDF ti ashıw",
  },
};

function safeUrl(value: string | null) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

export function ResearchPanel({ projectId }: { projectId: string }) {
  const { locale } = useLocale();
  const t = COPY[locale];
  const { withAuth } = useAppSession();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<ResearchView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2 || busy) return;
    setBusy(true);
    setError(false);
    setResult(null);
    try {
      const data = await withAuth((token) =>
        searchResearch(projectId, query, token),
      );
      if (data) setResult(data);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="research-panel">
      <h3>{t.title}</h3>
      <p>{t.note}</p>
      <form onSubmit={search}>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t.placeholder}
          aria-label={t.placeholder}
          minLength={2}
          maxLength={500}
          required
        />
        <button disabled={busy}>
          <Search size={16} />
          {busy ? t.busy : t.search}
        </button>
      </form>
      <small>Crossref · OpenAlex · Semantic Scholar · arXiv</small>
      <p className="research-legal">
        {t.legal}{" "}
        <a
          href={lexUzSearchUrl(query, locale)}
          target="_blank"
          rel="noreferrer"
        >
          {t.legalLink} <ExternalLink size={12} />
        </a>
      </p>
      {error && <p role="alert">{t.error}</p>}
      {result && (
        <div aria-live="polite">
          {result.unavailable_providers.length > 0 && (
            <p>
              {t.partial} {result.unavailable_providers.join(", ")}
            </p>
          )}
          {!result.papers.length && <p>{t.empty}</p>}
          {result.papers.map((paper, index) => {
            const pdf = safeUrl(paper.pdf_url);
            const doi = paper.doi
              ? `https://doi.org/${encodeURIComponent(paper.doi)}`
              : null;
            return (
              <article
                key={`${paper.source_api}-${paper.external_id}-${index}`}
              >
                <small>
                  {paper.source_api} · {paper.year ?? "—"}
                </small>
                <h4>{paper.title}</h4>
                <p>{paper.authors.join(", ")}</p>
                {paper.abstract && (
                  <details>
                    <summary>{t.abstract}</summary>
                    <p>{paper.abstract}</p>
                  </details>
                )}
                <div>
                  {doi && (
                    <a href={doi} target="_blank" rel="noreferrer">
                      {t.open}
                      <ExternalLink size={12} />
                    </a>
                  )}
                  {pdf && (
                    <a href={pdf} target="_blank" rel="noreferrer">
                      {t.download}
                      <ExternalLink size={12} />
                    </a>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
