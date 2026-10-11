"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  Download,
  History,
  Link2,
  Plus,
  Quote,
  Trash2,
} from "lucide-react";
import {
  downloadArticleDocx,
  getArticleRevisions,
  type ArticleBlockType,
  type DocumentRevision,
} from "@/lib/api";
import { articleEvidenceRows, attachPassage, detachCitation } from "@/lib/article-evidence";
import { addBlock, moveBlock, removeBlock, wordCount } from "@/lib/article-editor";
import { useArticleDocument } from "@/lib/use-article-document";
import { useAppSession } from "@/lib/use-session";
import { useLocale } from "./locale-provider";
import { EvidenceMap } from "./evidence-graph";
import { ResearchPanel } from "./research-panel";
import { EvidenceLibrary } from "./evidence-library";
import { ARTICLE_COPY } from "./article-workspace-copy";
import "./article-workspace.css";

interface ArticleWorkspaceProps {
  projectId: string;
  title: string;
  sourcePanel?: ReactNode;
  sourceCount?: number;
}

export function ArticleWorkspace({
  projectId,
  title,
  sourcePanel,
  sourceCount = 0,
}: ArticleWorkspaceProps) {
  const { locale } = useLocale();
  const t = ARTICLE_COPY[locale];
  const { withAuth } = useAppSession();
  const article = useArticleDocument(projectId, title);
  const { document, content, state, load, recovery, deviceCopy, update } = article;
  const [history, setHistory] = useState<DocumentRevision[] | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(false);
  const [citationTarget, setCitationTarget] = useState<string | null>(null);
  const [inspectPassage, setInspectPassage] = useState<string | null>(null);
  const targetExists = !citationTarget || Boolean(content?.blocks.some((block) => block.id === citationTarget));

  useEffect(() => {
    if (!targetExists) setCitationTarget(null);
  }, [targetExists]);

  function updateBlock(
    id: string,
    patch: Partial<NonNullable<typeof content>["blocks"][number]>,
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
    setHistory(null);
    setHistoryError(null);
    try {
      const result = await withAuth((token) => getArticleRevisions(projectId, token));
      if (result) setHistory(result.revisions);
    } catch {
      setHistoryError(t.historyError);
    }
  }
  async function restore(revisionId: string) {
    const outcome = await article.restore(revisionId);
    if (outcome === "ok") setHistoryOpen(false);
    else setHistoryError(outcome === "blocked" ? t.restoreBlocked : t.restoreError);
  }
  async function exportDocx() {
    if (exporting || state !== "saved" || !content?.title.trim() || !document) return;
    setExporting(true);
    setExportError(false);
    try {
      const blob = await withAuth((token) =>
        downloadArticleDocx(projectId, token, document.revision_id),
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
  if (load.kind === "failed")
    return (
      <div className="article-loading" role="alert">
        <p>{t.loadFailed}</p>
        {load.hasDraft && <p>{t.loadDraft}</p>}
        <button onClick={article.reopen}>{t.tryAgain}</button>
      </div>
    );
  if (!content || !document)
    return <div className="article-loading">{t.loading}</div>;
  const headings = content.blocks.filter(
    (block) => block.type === "heading" && block.text.trim(),
  );
  const evidenceRows = articleEvidenceRows(content);
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
      {state === "error" && (
        <div className="article-alert" role="alert">
          <span>{deviceCopy ? t.errorDevice : t.errorNoDevice}</span>
          <button onClick={article.retry}>{t.retryNow}</button>
        </div>
      )}
      {state === "conflict" && (
        <div className="article-alert" role="alert">
          <span>{t.conflictBody} {t.keepMineHint}</span>
          <button onClick={() => void article.keepMine()}>{t.keepMine}</button>
          <button onClick={() => void article.takeSaved()}>{t.useSaved}</button>
        </div>
      )}
      {state === "rejected" && (
        <div className="article-alert" role="alert">
          <span>{t.rejectedBody}</span>
          <button onClick={() => void article.takeSaved()}>{t.useSaved}</button>
        </div>
      )}
      {recovery?.kind === "resumed" && state !== "conflict" && (
        <div className="article-alert article-notice" role="status">
          <span>{t.resumed}</span>
          <button onClick={() => void article.takeSaved()}>{t.discard}</button>
          <button onClick={article.dismissRecovery}>{t.close}</button>
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
                className={`article-block ${block.type} ${citationTarget === block.id ? "citation-target" : ""}`}
                key={block.id}
              >
                <div className="article-block-tools">
                  <select
                    aria-label={t.blockType}
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
                  <button aria-label={t.addSource} title={t.addSource} onClick={() => {
                    setCitationTarget(block.id);
                    window.document.getElementById("article-source-library")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                  }}><Link2 size={14} />{t.addSource}</button>
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
                      <span key={citation.passage_id ?? citation.claim_id}>
                        {citation.passage_id ? <button onClick={() => {
                          setInspectPassage(citation.passage_id!);
                          window.document.getElementById("article-source-library")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                        }}>{citation.label}</button> : citation.label}
                        <button aria-label={`${t.removeSource}: ${citation.label}`} onClick={() => update(detachCitation(content, block.id, (citation.passage_id ?? citation.claim_id)!))}>×</button>
                      </span>
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
          <EvidenceLibrary projectId={projectId} refreshKey={sourceCount}
            selectedBlock={content.blocks.find((block) => block.id === citationTarget)}
            inspectId={inspectPassage} onCloseInspect={() => setInspectPassage(null)}
            onCancel={() => setCitationTarget(null)}
            onAttach={(passage, filename) => {
              if (citationTarget) update(attachPassage(content, citationTarget, passage, filename));
            }} />
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
            {historyError && <p role="alert">{historyError}</p>}
            {state !== "saved" && <p>{t.restoreBlocked}</p>}
            {history === null ? (
              !historyError && <p>{t.loading}</p>
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
                      <button disabled={state !== "saved"} onClick={() => void restore(revision.id)}>
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
