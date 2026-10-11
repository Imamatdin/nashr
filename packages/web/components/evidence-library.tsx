"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getEvidence, getEvidencePassage, processEvidence, type ArticleBlock, type EvidencePassage, type EvidenceView } from "@/lib/api";
import { useAppSession } from "@/lib/use-session";
import { useLocale } from "./locale-provider";
import { EVIDENCE_COPY } from "./evidence-library-copy";
import "./evidence-library.css";

function failedSourceIds(progress: Record<string, unknown>): string[] {
  const ids = progress.failed_sources;
  return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : [];
}

interface Props {
  projectId: string;
  refreshKey: number;
  selectedBlock: ArticleBlock | undefined;
  inspectId: string | null;
  onAttach: (passage: EvidencePassage, filename: string) => void;
  onCancel: () => void;
  onCloseInspect: () => void;
}

export function EvidenceLibrary({ projectId, refreshKey, selectedBlock, inspectId, onAttach, onCancel, onCloseInspect }: Props) {
  const { locale } = useLocale();
  const t = EVIDENCE_COPY[locale];
  const { withAuth } = useAppSession();
  const [view, setView] = useState<EvidenceView | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);
  const [inspected, setInspected] = useState<EvidencePassage | null>(null);
  const [inspectError, setInspectError] = useState(false);
  const sequence = useRef(0);
  const active = view?.job?.status === "queued" || view?.job?.status === "processing";

  const refresh = useCallback(async (offset = 0) => {
    const request = ++sequence.current;
    setLoading(true);
    setError(false);
    try {
      const next = await withAuth((token) => getEvidence(projectId, token, sourceId, offset));
      if (!next || request !== sequence.current) return;
      setView((previous) => ({ ...next, passages: offset ? [...(previous?.passages ?? []), ...next.passages] : next.passages }));
    } catch {
      if (request === sequence.current) setError(true);
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }, [projectId, sourceId, withAuth]);

  useEffect(() => {
    setView(null);
    void refresh();
    return () => { sequence.current += 1; };
  }, [refresh, refreshKey]);
  useEffect(() => {
    if (!active || loading || error) return;
    const timer = window.setTimeout(() => void refresh(), 2000);
    return () => window.clearTimeout(timer);
  }, [active, loading, error, refresh]);
  useEffect(() => {
    let cancelled = false;
    setInspected(null);
    setInspectError(false);
    if (inspectId) {
      void withAuth((token) => getEvidencePassage(projectId, inspectId, token)).then((passage) => {
        if (!cancelled) setInspected(passage);
      }).catch(() => { if (!cancelled) setInspectError(true); });
    }
    return () => { cancelled = true; };
  }, [inspectId, projectId, withAuth]);

  async function process() {
    if (active || submitting) return;
    setSubmitting(true);
    setError(false);
    try {
      const job = await withAuth((token) => processEvidence(projectId, token));
      if (job) await refresh();
    } catch {
      setError(true);
    } finally {
      setSubmitting(false);
    }
  }
  const pending = view?.sources.some((source) => !source.processed_at);
  const failedIds = new Set(view?.job?.status === "failed" ? failedSourceIds(view.job.progress) : []);
  function passageCard(passage: EvidencePassage, inspection = false) {
    const filename = view?.sources.find((source) => source.id === passage.source_id)?.filename ?? t.inspect;
    const attached = selectedBlock?.citations.some((citation) => citation.passage_id === passage.id);
    return <article key={passage.id} className="source-passage">
      <strong>{filename}</strong>
      <small>{passage.page ? `${t.page} ${passage.page}` : `${t.passage} ${passage.chunk_index + 1}`}</small>
      {passage.is_ocr && <small className={passage.confidence < 60 ? "evidence-warning" : ""}>{t.ocr} · {Math.round(passage.confidence)}%{passage.confidence < 60 ? ` · ${t.low}` : ""}</small>}
      <blockquote>{passage.text}</blockquote>
      {!inspection && <button disabled={!selectedBlock || attached || selectedBlock.citations.length >= 100} onClick={() => onAttach(passage, filename)}>{attached ? t.attached : t.cite}</button>}
    </article>;
  }
  return <section id="article-source-library" className="evidence-library" aria-label={t.title}>
    <header><h3>{t.title}</h3><button disabled={loading} onClick={() => void refresh()}>{t.refresh}</button></header>
    <p>{t.intro}</p>
    <button className="evidence-process" disabled={!pending || active || submitting} onClick={() => void process()}>
      {active || submitting ? t.working : view?.job?.status === "failed" ? t.retry : t.process}
    </button>
    {view?.job?.status === "failed" && <p role="alert" className="evidence-warning">{failedIds.size ? t.failedSome : t.failed}</p>}
    {error && <p role="alert">{t.error}</p>}
    {view?.sources.map((source) => <div className="evidence-source-status" key={source.id}>
      <span>{source.filename}</span><small className={!source.processed_at && failedIds.has(source.id) ? "evidence-warning" : ""}>{source.processed_at ? `${t.ready} · ${source.passage_count}` : failedIds.has(source.id) ? t.unreadable : t.pending}</small>
      {source.warnings.length > 0 && <details><summary>{t.ocr}</summary>{source.warnings.map((warning, index) => <p key={index}>{warning}</p>)}</details>}
    </div>)}
    {view && !view.sources.length && <p>{t.empty}</p>}
    {view && view.sources.length > 1 && <select aria-label={t.all} value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
      <option value="">{t.all}</option>{view.sources.map((source) => <option value={source.id} key={source.id}>{source.filename}</option>)}
    </select>}
    <div className="evidence-selection" aria-live="polite">{selectedBlock ? <>
      <strong>{t.selected}</strong><p>{selectedBlock.text.slice(0, 120) || "…"}</p><button onClick={onCancel}>{t.cancel}</button>
    </> : t.select}</div>
    {inspectId && <aside className="evidence-inspected" aria-label={t.inspect}>
      <button onClick={onCloseInspect}>{t.close}</button>
      {inspectError ? <p role="alert">{t.invalid}</p> : inspected ? passageCard(inspected, true) : <p>{t.loading}</p>}
    </aside>}
    <div className="evidence-passages">{view?.passages.map((passage) => passageCard(passage))}</div>
    {loading && <p role="status">{t.loading}</p>}
    {view?.next_offset != null && <button disabled={loading || active} onClick={() => void refresh(view.next_offset!)}>{t.more}</button>}
  </section>;
}
