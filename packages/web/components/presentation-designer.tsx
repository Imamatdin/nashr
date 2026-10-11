"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Check,
  ExternalLink,
  History,
  MonitorPlay,
  Paintbrush,
} from "lucide-react";
import {
  ApiError,
  getDesign,
  getDesignRevisions,
  getJob,
  renderDesign,
  restoreDesign,
  saveDesign,
  type DeckAccessView,
  type DesignDeck,
  type DesignDocumentView,
  type DocumentRevision,
} from "@/lib/api";
import { shownExports } from "@/lib/deck-exports";
import { useAppSession } from "@/lib/use-session";
import { useLocale } from "./locale-provider";
import {
  SlideCanvas,
  SlideRail,
  PropertiesPanel,
} from "./presentation-design-surface";
import { DesignHistory } from "./presentation-design-history";
import { ProposalsPanel } from "./presentation-proposals";
import { DESIGNER_COPY } from "./presentation-designer-copy";
import "./presentation-designer.css";

type SaveState = "saved" | "dirty" | "saving" | "conflict" | "error";
const SAVE_DELAY_MS = 900;

export function PresentationDesigner({
  projectId,
  deck,
  onRendered,
}: {
  projectId: string;
  deck: DeckAccessView;
  onRendered: () => void;
}) {
  const { locale } = useLocale();
  const t = DESIGNER_COPY[locale];
  const { withAuth } = useAppSession();
  const [view, setView] = useState<DesignDocumentView | null>(null);
  const [content, setContent] = useState<DesignDeck | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [state, setState] = useState<SaveState>("saved");
  const [mode, setMode] = useState<"canvas" | "preview">("canvas");
  const [renderJob, setRenderJob] = useState<string | null>(null);
  const [renderState, setRenderState] = useState<
    "idle" | "rendering" | "rendered" | "error"
  >("idle");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<DocumentRevision[] | null>(null);
  const [historyError, setHistoryError] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const contentRef = useRef<DesignDeck | null>(null);
  const viewRef = useRef<DesignDocumentView | null>(null);
  const versionRef = useRef(0);
  const savingRef = useRef(false);
  contentRef.current = content;
  viewRef.current = view;
  const load = useCallback(async () => {
    const result = await withAuth((token) => getDesign(projectId, token));
    if (!result) return;
    versionRef.current = 0;
    setView(result);
    setContent(result.content);
    setSelected((current) =>
      result.content.slides.some((slide) => slide.slide_id === current)
        ? current
        : (result.content.slides[0]?.slide_id ?? null),
    );
    setState("saved");
  }, [projectId, withAuth]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (state !== "dirty" || !content || !view || savingRef.current) return;
    if (
      !content.title.trim() ||
      content.slides.some((slide) => !slide.content.title.trim())
    )
      return;
    const timer = window.setTimeout(async () => {
      const nextContent = contentRef.current;
      const base = viewRef.current;
      if (!nextContent || !base || savingRef.current) return;
      const version = versionRef.current;
      savingRef.current = true;
      setState("saving");
      try {
        const next = await withAuth((token) =>
          saveDesign(
            projectId,
            base.revision_id,
            nextContent,
            crypto.randomUUID(),
            token,
          ),
        );
        if (!next) return;
        setView(next);
        setState(versionRef.current === version ? "saved" : "dirty");
      } catch (error) {
        // A 409 means the head moved under this editor (ADR 0001): reload
        // rather than overwrite. Manual edits are never locked out by an AI
        // edit any more; that one becomes a proposal instead.
        setState(error instanceof ApiError && error.status === 409 ? "conflict" : "error");
      } finally {
        savingRef.current = false;
      }
    }, SAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [content, projectId, state, view, withAuth]);
  useEffect(() => {
    if (!renderJob) return;
    const timer = window.setInterval(() => {
      void withAuth((token) => getJob(renderJob, token))
        .then((job) => {
          if (!job) return;
          if (job.status === "completed") {
            window.clearInterval(timer);
            setRenderJob(null);
            setRenderState("rendered");
            onRendered();
          } else if (job.status === "failed" || job.status === "cancelled") {
            window.clearInterval(timer);
            setRenderJob(null);
            setRenderState("error");
          }
        })
        .catch(() => {
          window.clearInterval(timer);
          setRenderJob(null);
          setRenderState("error");
        });
    }, 1800);
    return () => window.clearInterval(timer);
  }, [onRendered, renderJob, withAuth]);
  function update(next: DesignDeck) {
    versionRef.current += 1;
    setContent(next);
    setState("dirty");
    setRenderState("idle");
  }
  function updateSlide(patch: Record<string, unknown>) {
    if (!content || !selected) return;
    update({
      ...content,
      slides: content.slides.map((slide) =>
        slide.slide_id === selected
          ? { ...slide, content: { ...slide.content, ...patch } }
          : slide,
      ),
    });
  }
  function move(delta: -1 | 1) {
    if (!content || !selected) return;
    const index = content.slides.findIndex(
      (slide) => slide.slide_id === selected,
    );
    const target = index + delta;
    if (index < 0 || target < 0 || target >= content.slides.length) return;
    const slides = [...content.slides];
    [slides[index], slides[target]] = [slides[target], slides[index]];
    update({
      ...content,
      slides: slides.map((slide, slide_index) => ({ ...slide, slide_index })),
    });
  }
  function duplicate() {
    if (!content || !selected) return;
    const index = content.slides.findIndex(
      (slide) => slide.slide_id === selected,
    );
    if (index < 0 || content.slides.length >= 50) return;
    const clone = {
      ...structuredClone(content.slides[index]),
      slide_id: crypto.randomUUID(),
    };
    const slides = [
      ...content.slides.slice(0, index + 1),
      clone,
      ...content.slides.slice(index + 1),
    ].map((slide, slide_index) => ({ ...slide, slide_index }));
    update({ ...content, slides });
    setSelected(clone.slide_id);
  }
  function remove() {
    if (!content || !selected || content.slides.length <= 1) return;
    const index = content.slides.findIndex(
      (slide) => slide.slide_id === selected,
    );
    const slides = content.slides
      .filter((slide) => slide.slide_id !== selected)
      .map((slide, slide_index) => ({ ...slide, slide_index }));
    update({ ...content, slides });
    setSelected(slides[Math.min(index, slides.length - 1)].slide_id);
  }
  async function openHistory() {
    if (state !== "saved") return;
    setHistoryOpen(true);
    setHistory(null);
    setHistoryError(false);
    try {
      const result = await withAuth((token) =>
        getDesignRevisions(projectId, token),
      );
      if (result) setHistory(result.revisions);
    } catch {
      setHistoryError(true);
    }
  }
  async function restore(revisionId: string) {
    if (!view || restoring) return;
    setRestoring(true);
    try {
      const next = await withAuth((token) =>
        restoreDesign(
          projectId,
          revisionId,
          view.revision_id,
          crypto.randomUUID(),
          token,
        ),
      );
      if (!next) return;
      versionRef.current = 0;
      setView(next);
      setContent(next.content);
      setSelected(next.content.slides[0]?.slide_id ?? null);
      setState("saved");
      setRenderState("idle");
      setHistoryOpen(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setState("conflict");
        setHistoryOpen(false);
      } else {
        setHistoryError(true);
      }
    } finally {
      setRestoring(false);
    }
  }
  async function render() {
    if (!view || state !== "saved" || renderJob) return;
    setRenderState("rendering");
    try {
      const result = await withAuth((token) =>
        renderDesign(projectId, view.revision_id, token),
      );
      if (result) setRenderJob(result.job_id);
    } catch {
      setRenderState("error");
    }
  }
  if (!content || !view)
    return <div className="designer-loading">{t.opening}</div>;
  const slide =
    content.slides.find((item) => item.slide_id === selected) ??
    content.slides[0];
  // Only the head's own exports are presented as current; an older export is
  // shown only with a label saying which kind of older it is (ADR 0001).
  const shown = shownExports(deck);
  const exports = shown.exports;
  const previewNote = shown.notice ? t[shown.notice] : null;
  return (
    <section className="designer">
      <header className="designer-bar">
        <div className={`designer-save ${state}`}>
          {state === "saved" && <Check size={14} />} {t[state]}
        </div>
        <div className="designer-modes">
          <button
            data-active={mode === "canvas"}
            onClick={() => setMode("canvas")}
          >
            <Paintbrush size={15} />
            {t.canvas}
          </button>
          <button
            data-active={mode === "preview"}
            onClick={() => setMode("preview")}
          >
            <MonitorPlay size={15} />
            {t.preview}
          </button>
        </div>
        <button
          className="designer-history-trigger"
          disabled={state !== "saved"}
          onClick={() => void openHistory()}
        >
          <History size={15} />
          {t.history}
        </button>
        <button
          className="designer-render"
          disabled={state !== "saved" || !!renderJob}
          onClick={() => void render()}
        >
          {renderState === "rendering" ? t.rendering : t.render}
        </button>
      </header>
      {(state === "conflict" || state === "error") && (
        <div className="designer-alert">
          <span>{t[state]}</span>
          <button onClick={() => void load()}>{t.reload}</button>
        </div>
      )}
      {renderState === "rendered" && (
        <p className="designer-render-note success">{t.rendered}</p>
      )}
      {renderState === "error" && (
        <p className="designer-render-note error">{t.renderError}</p>
      )}
      <div className="designer-grid">
        <SlideRail
          deck={content}
          selected={slide.slide_id}
          label={t.slides}
          onSelect={setSelected}
        />
        <SlideCanvas
          deck={content}
          slide={slide}
          mode={mode}
          htmlUrl={exports?.html_url ?? null}
          previewNote={previewNote}
          previewLabel={t.preview}
          onTitle={(title) => updateSlide({ title })}
        />
        <PropertiesPanel
          deck={content}
          slide={slide}
          copy={t}
          onSlide={updateSlide}
          onDeck={update}
          onMove={move}
          onDuplicate={duplicate}
          onRemove={remove}
        />
      </div>
      <footer className="designer-downloads">
        {deck.state === "render_needed" && (
          <p className="designer-render-needed" role="status">
            {t.renderNeeded}
          </p>
        )}
        {previewNote && deck.fallback && (
          <p className="designer-fallback-note">{previewNote}</p>
        )}
        {(exports?.downloads ?? []).map((item) => (
          <a key={item.format} href={item.url} download>
            <ExternalLink size={14} />
            {t.download} {item.format.toUpperCase()}
          </a>
        ))}
      </footer>
      <ProposalsPanel
        projectId={projectId}
        copy={t}
        onAccepted={() => {
          void load();
          onRendered();
        }}
      />
      {historyOpen && (
        <DesignHistory
          revisions={history}
          currentRevisionId={view.revision_id}
          copy={t}
          locale={locale}
          error={historyError}
          restoring={restoring}
          onClose={() => setHistoryOpen(false)}
          onRestore={(revisionId) => void restore(revisionId)}
        />
      )}
    </section>
  );
}
