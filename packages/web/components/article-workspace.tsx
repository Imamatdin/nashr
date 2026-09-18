"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  Download,
  History,
  Plus,
  Quote,
  Trash2,
} from "lucide-react";
import {
  ApiError,
  downloadArticleDocx,
  getArticle,
  getArticleRevisions,
  initializeArticle,
  restoreArticle,
  saveArticle,
  type ArticleBlockType,
  type ArticleContent,
  type ArticleDocumentView,
  type DocumentRevision,
  type ProvenanceRow,
} from "@/lib/api";
import {
  addBlock,
  moveBlock,
  newBlock,
  removeBlock,
  wordCount,
} from "@/lib/article-editor";
import { useAppSession } from "@/lib/use-session";
import { useLocale } from "./locale-provider";
import { EvidenceMap } from "./evidence-graph";
import { ResearchPanel } from "./research-panel";
import "./article-workspace.css";

type SaveState = "saved" | "dirty" | "saving" | "conflict" | "error";
const COPY = {
  en: {
    document: "Document",
    outline: "Outline",
    research: "Research",
    saved: "Saved",
    dirty: "Unsaved changes",
    saving: "Saving…",
    conflict: "This article changed elsewhere. Reload before continuing.",
    error: "Could not save. Your changes are still on this device.",
    reload: "Reload current version",
    history: "Version history",
    restore: "Restore",
    add: "Add block",
    paragraph: "Paragraph",
    heading: "Heading",
    quote: "Quote",
    bullet: "Bullet",
    words: "words",
    empty: "Start writing here",
    title: "Article title",
    delete: "Delete block",
    up: "Move up",
    down: "Move down",
    close: "Close",
    loading: "Opening your document…",
    export: "Download DOCX",
    exporting: "Preparing…",
    exportError: "Could not prepare the Word file.",
  },
  ru: {
    document: "Документ",
    outline: "Структура",
    research: "Исследования",
    saved: "Сохранено",
    dirty: "Есть несохранённые изменения",
    saving: "Сохранение…",
    conflict:
      "Статья изменилась в другом окне. Обновите версию перед продолжением.",
    error: "Не удалось сохранить. Изменения остались на этом устройстве.",
    reload: "Загрузить текущую версию",
    history: "История версий",
    restore: "Восстановить",
    add: "Добавить блок",
    paragraph: "Абзац",
    heading: "Заголовок",
    quote: "Цитата",
    bullet: "Список",
    words: "слов",
    empty: "Начните писать",
    title: "Название статьи",
    delete: "Удалить блок",
    up: "Выше",
    down: "Ниже",
    close: "Закрыть",
    loading: "Открываем документ…",
    export: "Скачать DOCX",
    exporting: "Подготовка…",
    exportError: "Не удалось подготовить файл Word.",
  },
  uz: {
    document: "Hujjat",
    outline: "Tuzilma",
    research: "Tadqiqot",
    saved: "Saqlandi",
    dirty: "Saqlanmagan o‘zgarishlar",
    saving: "Saqlanmoqda…",
    conflict:
      "Maqola boshqa oynada o‘zgargan. Davom etishdan oldin joriy versiyani yuklang.",
    error: "Saqlab bo‘lmadi. O‘zgarishlar shu qurilmada turibdi.",
    reload: "Joriy versiyani yuklash",
    history: "Versiyalar tarixi",
    restore: "Tiklash",
    add: "Blok qo‘shish",
    paragraph: "Xatboshi",
    heading: "Sarlavha",
    quote: "Iqtibos",
    bullet: "Ro‘yxat",
    words: "so‘z",
    empty: "Yozishni boshlang",
    title: "Maqola nomi",
    delete: "Blokni o‘chirish",
    up: "Yuqoriga",
    down: "Pastga",
    close: "Yopish",
    loading: "Hujjat ochilmoqda…",
    export: "DOCX yuklash",
    exporting: "Tayyorlanmoqda…",
    exportError: "Word faylini tayyorlab bo‘lmadi.",
  },
};
const SAVE_DELAY_MS = 900;

interface ArticleWorkspaceProps {
  projectId: string;
  title: string;
  sourcePanel?: ReactNode;
  evidenceRows?: ProvenanceRow[];
}

export function ArticleWorkspace({
  projectId,
  title,
  sourcePanel,
  evidenceRows = [],
}: ArticleWorkspaceProps) {
  const { locale } = useLocale();
  const t = COPY[locale];
  const { withAuth } = useAppSession();
  const [document, setDocument] = useState<ArticleDocumentView | null>(null);
  const [content, setContent] = useState<ArticleContent | null>(null);
  const [state, setState] = useState<SaveState>("saved");
  const [history, setHistory] = useState<DocumentRevision[] | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(false);
  const contentRef = useRef<ArticleContent | null>(null);
  const documentRef = useRef<ArticleDocumentView | null>(null);
  const editVersionRef = useRef(0);
  const savingRef = useRef(false);
  contentRef.current = content;
  documentRef.current = document;

  const load = useCallback(async () => {
    const view = await withAuth(async (token) => {
      try {
        return await getArticle(projectId, token);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          return initializeArticle(
            projectId,
            title,
            `init:${projectId}`,
            token,
          );
        }
        throw error;
      }
    });
    if (!view) return;
    const initial = view.content.blocks.length
      ? view.content
      : {
          ...view.content,
          blocks: [newBlock("heading"), newBlock("paragraph")],
        };
    editVersionRef.current = 0;
    setDocument(view);
    setContent(initial);
    setState(initial === view.content ? "saved" : "dirty");
  }, [projectId, title, withAuth]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (state !== "dirty" || !content || !document) return;
    const timer = window.setTimeout(async () => {
      const savingContent = contentRef.current;
      const base = documentRef.current;
      if (
        !savingContent ||
        !base ||
        !savingContent.title.trim() ||
        savingRef.current
      )
        return;
      const savingVersion = editVersionRef.current;
      savingRef.current = true;
      setState("saving");
      try {
        const next = await withAuth((token) =>
          saveArticle(
            projectId,
            base.revision_id,
            savingContent,
            crypto.randomUUID(),
            token,
          ),
        );
        if (!next) return;
        setDocument(next);
        setState(editVersionRef.current === savingVersion ? "saved" : "dirty");
      } catch (error) {
        setState(
          error instanceof ApiError && error.status === 409
            ? "conflict"
            : "error",
        );
      } finally {
        savingRef.current = false;
      }
    }, SAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [content, document, projectId, state, withAuth]);

  function update(next: ArticleContent) {
    editVersionRef.current += 1;
    setContent(next);
    setState("dirty");
  }
  function updateBlock(
    id: string,
    patch: Partial<ArticleContent["blocks"][number]>,
  ) {
    if (!content) return;
    update({
      ...content,
      blocks: content.blocks.map((block) =>
        block.id === id ? { ...block, ...patch } : block,
      ),
    });
  }
  async function openHistory() {
    setHistoryOpen(true);
    const result = await withAuth((token) =>
      getArticleRevisions(projectId, token),
    );
    if (result) setHistory(result.revisions);
  }
  async function restore(revisionId: string) {
    if (!document) return;
    const view = await withAuth((token) =>
      restoreArticle(
        projectId,
        revisionId,
        document.revision_id,
        crypto.randomUUID(),
        token,
      ),
    );
    if (view) {
      setDocument(view);
      setContent(view.content);
      setState("saved");
      setHistoryOpen(false);
    }
  }
  async function exportDocx() {
    if (exporting || state !== "saved" || !content?.title.trim()) return;
    setExporting(true);
    setExportError(false);
    try {
      const blob = await withAuth((token) =>
        downloadArticleDocx(projectId, token),
      );
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = `${content.title}.docx`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setExportError(true);
    } finally {
      setExporting(false);
    }
  }
  if (!content || !document)
    return <div className="article-loading">{t.loading}</div>;
  const headings = content.blocks.filter(
    (block) => block.type === "heading" && block.text.trim(),
  );
  const labels: Record<ArticleBlockType, string> = {
    paragraph: t.paragraph,
    heading: t.heading,
    quote: t.quote,
    bullet: t.bullet,
  };
  return (
    <div className="article-shell">
      <header className="article-topbar">
        <input
          aria-label={t.title}
          value={content.title}
          maxLength={300}
          onChange={(event) =>
            update({ ...content, title: event.target.value })
          }
        />
        <div className={`article-save ${state}`}>
          {state === "saved" && <Check size={14} />}{" "}
          {content.title.trim() ? t[state] : t.dirty}
        </div>
        <button onClick={() => void openHistory()}>
          <History size={16} />
          {t.history}
        </button>
        <button
          disabled={exporting || state !== "saved"}
          onClick={() => void exportDocx()}
        >
          <Download size={16} />
          {exporting ? t.exporting : t.export}
        </button>
      </header>
      {exportError && (
        <div className="article-alert" role="alert">
          <span>{t.exportError}</span>
          <button onClick={() => setExportError(false)}>{t.close}</button>
        </div>
      )}
      {(state === "conflict" || state === "error") && (
        <div className="article-alert" role="alert">
          <span>{t[state]}</span>
          <button onClick={() => void load()}>{t.reload}</button>
        </div>
      )}
      <div className="article-grid">
        <aside className="article-outline">
          <strong>{t.outline}</strong>
          {headings.length ? (
            headings.map((block, index) => (
              <a key={block.id} href={`#block-${block.id}`}>
                {index + 1}. {block.text}
              </a>
            ))
          ) : (
            <p>{t.empty}</p>
          )}
          <small>
            {wordCount(content)} {t.words}
          </small>
        </aside>
        <main className="article-canvas">
          <div className="article-page">
            {content.blocks.map((block, index) => (
              <div
                id={`block-${block.id}`}
                className={`article-block ${block.type}`}
                key={block.id}
              >
                <div className="article-block-tools">
                  <select
                    aria-label="Block type"
                    value={block.type}
                    onChange={(event) =>
                      updateBlock(block.id, {
                        type: event.target.value as ArticleBlockType,
                        level: event.target.value === "heading" ? 2 : null,
                      })
                    }
                  >
                    {Object.entries(labels).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <button
                    aria-label={t.up}
                    disabled={index === 0}
                    onClick={() => update(moveBlock(content, block.id, -1))}
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    aria-label={t.down}
                    disabled={index === content.blocks.length - 1}
                    onClick={() => update(moveBlock(content, block.id, 1))}
                  >
                    <ArrowDown size={14} />
                  </button>
                  <button
                    aria-label={t.delete}
                    disabled={content.blocks.length === 1}
                    onClick={() => update(removeBlock(content, block.id))}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <textarea
                  value={block.text}
                  placeholder={block.type === "heading" ? t.heading : t.empty}
                  rows={block.type === "heading" ? 1 : 3}
                  onChange={(event) =>
                    updateBlock(block.id, { text: event.target.value })
                  }
                />
                {block.citations.length > 0 && (
                  <div className="article-citations">
                    {block.citations.map((citation) => (
                      <span key={citation.claim_id}>{citation.label}</span>
                    ))}
                  </div>
                )}
                <button
                  className="article-insert"
                  aria-label={t.add}
                  onClick={() =>
                    update(addBlock(content, block.id, "paragraph"))
                  }
                >
                  <Plus size={14} />
                </button>
              </div>
            ))}
          </div>
        </main>
        <aside className="article-side">
          {sourcePanel}
          <ResearchPanel projectId={projectId} />
          <div className="article-source-note">
            <Quote size={16} />
            <p>{t.research}</p>
          </div>
        </aside>
      </div>
      {evidenceRows.length > 0 && (
        <div className="article-evidence">
          <EvidenceMap rows={evidenceRows} />
        </div>
      )}
      {historyOpen && (
        <div
          className="article-history"
          role="dialog"
          aria-modal="true"
          aria-label={t.history}
        >
          <div>
            <header>
              <h2>{t.history}</h2>
              <button onClick={() => setHistoryOpen(false)}>{t.close}</button>
            </header>
            {history === null ? (
              <p>{t.loading}</p>
            ) : (
              <ol>
                {history.map((revision, index) => (
                  <li key={revision.id}>
                    <div>
                      <strong>
                        {index === 0
                          ? t.saved
                          : new Date(revision.created_at).toLocaleString(
                              locale,
                            )}
                      </strong>
                      <small>{revision.content_hash.slice(0, 8)}</small>
                    </div>
                    {revision.id !== document.revision_id && (
                      <button onClick={() => void restore(revision.id)}>
                        {t.restore}
                      </button>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
