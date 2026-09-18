"use client";

import { useMemo, useState } from "react";
import { useLocale } from "./locale-provider";
import { buildEvidenceGraph } from "@/lib/evidence-graph";
import type { ProvenanceRow } from "@/lib/api";
import "./evidence-graph.css";

const COPY = {
  en: { title: "Evidence map", search: "Find a claim or source", sources: "Sources", claims: "Claims", hint: "Lines show recorded source references, not independent verification. Select a node to inspect it.", unlinked: "No source linked", quote: "Recorded quotation", noQuote: "No quotation recorded. Check the original source.", chunk: "Source chunk", empty: "No matching claims. Add sources or change your search.", limit: "Showing the first 60 matching claims", close: "Clear selection" },
  ru: { title: "Карта доказательств", search: "Найти утверждение или источник", sources: "Источники", claims: "Утверждения", hint: "Линии показывают ссылки на источники, а не независимую проверку. Выберите узел для просмотра.", unlinked: "Источник не указан", quote: "Сохранённая цитата", noQuote: "Цитата не сохранена. Проверьте первоисточник.", chunk: "Фрагмент источника", empty: "Совпадений нет. Добавьте источники или измените запрос.", limit: "Показаны первые 60 найденных утверждений", close: "Снять выделение" },
  uz: { title: "Dalillar xaritasi", search: "Da’vo yoki manbani qidirish", sources: "Manbalar", claims: "Da’volar", hint: "Chiziqlar manbaga havolani bildiradi, mustaqil tekshiruvni emas. Tafsilot uchun tugunni tanlang.", unlinked: "Manba bog‘lanmagan", quote: "Saqlangan iqtibos", noQuote: "Iqtibos saqlanmagan. Asl manbani tekshiring.", chunk: "Manba bo‘lagi", empty: "Mos da’vo topilmadi. Manba qo‘shing yoki so‘rovni o‘zgartiring.", limit: "Dastlabki 60 ta mos da’vo ko‘rsatilgan", close: "Tanlovni bekor qilish" },
};

export function EvidenceMap({ rows }: { rows: ProvenanceRow[] }) {
  const { locale } = useLocale();
  const t = COPY[locale];
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const filtered = useMemo(() => rows.filter((row) => `${row.claim_text} ${row.source_filename ?? ""}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())), [rows, search]);
  const graph = useMemo(() => buildEvidenceGraph(filtered.slice(0, 60)), [filtered]);
  const sources = graph.nodes.filter((node) => node.kind === "source");
  const claims = graph.nodes.filter((node) => node.kind === "claim");
  const height = Math.max(260, claims.length * 64 + 60, sources.length * 64 + 60);
  const positions = new Map(graph.nodes.map((node) => {
    const group = node.kind === "source" ? sources : claims;
    return [node.id, { x: node.kind === "source" ? 130 : 530, y: 45 + group.indexOf(node) * (height - 80) / Math.max(1, group.length - 1) }];
  }));
  const current = graph.nodes.find((node) => node.id === selected);
  const neighbors = new Set(graph.edges.filter((edge) => edge.source === selected || edge.target === selected).flatMap((edge) => [edge.source, edge.target]));
  return <section className="evidence-map" aria-label={t.title}>
    <header><h3>{t.title}</h3><input aria-label={t.search} placeholder={t.search} value={search} onChange={(event) => { setSearch(event.target.value); setSelected(null); }} /></header>
    <p className="evidence-hint">{t.hint}</p>
    <div className="evidence-key"><span>{t.sources}</span><span>{t.claims}</span><span>{t.unlinked}</span></div>
    {!claims.length ? <p>{t.empty}</p> : <div className="evidence-scroll"><svg viewBox={`0 0 700 ${height}`} style={{ minHeight: height }} aria-label={t.title}>
      {graph.edges.map((edge) => {
        const a = positions.get(edge.source)!; const b = positions.get(edge.target)!;
        return <path key={`${edge.source}-${edge.target}`} d={`M${a.x},${a.y} C330,${a.y} 330,${b.y} ${b.x},${b.y}`} className={neighbors.has(edge.source) && neighbors.has(edge.target) ? "active-edge" : ""} />;
      })}
      {graph.nodes.map((node) => {
        const p = positions.get(node.id)!;
        return <g key={node.id} role="button" tabIndex={0} aria-label={node.label} aria-pressed={selected === node.id}
          className={`evidence-node ${node.kind} ${node.linked ? "" : "unlinked"} ${selected === node.id ? "selected" : ""}`}
          transform={`translate(${p.x},${p.y})`} onClick={() => setSelected(node.id)}
          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelected(node.id); } }}>
          <rect x={-115} y={-21} width={230} height={42} rx={9} /><circle cx={-99} cy={0} r={4} />
          <text x={-87} y={4}>{node.label.length > 31 ? `${node.label.slice(0, 30)}…` : node.label}</text><title>{node.label}</title>
        </g>;
      })}
    </svg></div>}
    {filtered.length > 60 && <p>{t.limit} ({filtered.length})</p>}
    {current && <aside className="evidence-inspect"><button onClick={() => setSelected(null)} aria-label={t.close}>×</button><strong>{current.label}</strong>
      {current.row && <><p>{current.row.source_filename || t.unlinked}{current.row.chunk_index !== null && ` · ${t.chunk} ${current.row.chunk_index}`}</p><small>{t.quote}</small><blockquote>{current.row.quote || t.noQuote}</blockquote></>}
    </aside>}
  </section>;
}
