"use client";

// The creation surface. One prompt box carries the whole flow: the topic is
// the prompt, sources are attachments on it, tier and language are pickers
// inside it. Past the composer the flow now has three beats instead of one —
// compose, clarify, approve — because the audit's §2.3 finding was that the
// only question ever asked was "shall we start?" while the pipeline quietly
// decided audience, length, emphasis, interactivity and notes style alone.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, GraduationCap, Presentation } from "lucide-react";
import { AppChrome } from "@/components/chrome";
import { ApprovalCard, PromptBar } from "@/components/bui";
import type { ApprovalAnswer, PromptPicker, PromptSource } from "@/components/bui";
import { Button } from "@/components/ui";
import {
  type PricingEntryView,
  type InterviewView,
  type SourceView,
  createProject,
  enqueueJob,
  getBalance,
  getInterview,
  getPricing,
  presignUpload,
  registerSource,
  uploadToR2WithProgress,
} from "@/lib/api";
import { creditCopy, describeError, rateLimitCopy, reasonOf } from "@/lib/errors";
import { useAppSession } from "@/lib/use-session";
import {
  type AnswerValue,
  CHARGE_NOTE,
  type DecisionSummary,
  type PreparedQuestion,
  buildAnswers,
  decisionSummary,
  planRows,
  prepareQuestions,
  submitBlock,
} from "@/lib/creation";
import {
  DEFAULT_LANGUAGE,
  DEFAULT_PACKAGE,
  LANGUAGES,
  type LanguageCode,
  PACKAGES,
  type PackageId,
  isLanguageCode,
  languageName,
  packageOf,
  soum,
} from "@/lib/packages";

import "./new.css";

const ACCEPTED = ".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv";
const MAX_SOURCES = 10;
const BOT_URL = "https://t.me/nashr_ai_bot";

type Stage = "compose" | "questions" | "confirm";
type InterviewState = "loading" | "ready" | "not_ready" | "error";

interface UploadRow {
  key: string;
  file: File;
  state: "pending" | "done" | "failed";
  /** 0…1 of the bytes that have left the browser. */
  progress: number;
  error: unknown;
  source: SourceView | null;
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * An error rendered where it happened, in human copy. Mirrors the workspace's
 * InlineError: the same catalogue, the same collapsible technical detail, so a
 * failure reads identically wherever the user meets it.
 */
function InlineError({
  error,
  onRetry,
  retryLabel,
  money,
  rate,
}: {
  error: unknown;
  onRetry?: () => void;
  retryLabel?: string;
  money?: boolean;
  rate?: boolean;
}) {
  const reason = reasonOf(error);
  const friendly =
    money && reason === "insufficient_balance"
      ? creditCopy(error, soum)
      : rate && reason === "rate_limited"
        ? rateLimitCopy(error)
        : describeError(error);

  return (
    <div className="new-inline-error" data-tone={friendly.tone} role="alert">
      <p className="new-inline-title">{friendly.title}</p>
      <p className="new-inline-message">{friendly.message}</p>
      {friendly.action?.kind === "topup" && (
        <p className="new-fine">
          To‘lov hozircha Telegram botda:{" "}
          <a href={BOT_URL} target="_blank" rel="noreferrer">
            botni ochish
          </a>
        </p>
      )}
      {onRetry && friendly.action?.kind !== "topup" && (
        <div className="new-inline-actions">
          <Button variant="ghost" onClick={onRetry}>
            {retryLabel ?? friendly.action?.label ?? "Qayta urinish"}
          </Button>
        </div>
      )}
      {friendly.detail && (
        <details className="new-detail">
          <summary>Texnik tafsilot</summary>
          <code>{friendly.detail}</code>
        </details>
      )}
    </div>
  );
}

function DecisionPanel({ summary }: { summary: DecisionSummary }) {
  return (
    <div className="new-decision">
      <p className="new-decision-lead">{summary.lead}</p>
      <ul className="new-decision-list">
        {summary.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

export default function NewProjectPage() {
  const router = useRouter();
  const { session, withAuth } = useAppSession();

  const [topic, setTopic] = useState("");
  const [language, setLanguage] = useState<LanguageCode>(DEFAULT_LANGUAGE);
  const [packageId, setPackageId] = useState<PackageId>(DEFAULT_PACKAGE);

  const [projectId, setProjectId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; danger?: boolean } | null>(null);

  const [uploads, setUploads] = useState<UploadRow[]>([]);
  /** Files picked before a topic existed. Held, never discarded (G30). */
  const [held, setHeld] = useState<File[]>([]);

  const [stage, setStage] = useState<Stage>("compose");
  const [interviewState, setInterviewState] = useState<InterviewState>("loading");
  const [interview, setInterview] = useState<InterviewView | null>(null);
  const [prepared, setPrepared] = useState<PreparedQuestion[]>([]);
  const [interviewError, setInterviewError] = useState<unknown>(null);
  const [answers, setAnswers] = useState<Record<string, AnswerValue> | undefined>(undefined);
  const [decided, setDecided] = useState<DecisionSummary | null>(null);

  const [pricing, setPricing] = useState<PricingEntryView[] | null>(null);
  const [balance, setBalance] = useState<number | null>(null);

  const [attempt, setAttempt] = useState(0);
  const [enqueueError, setEnqueueError] = useState<unknown>(null);
  const enqueuing = useRef(false);
  const uploadSeq = useRef(0);
  // The project is the parent every source hangs off: created once at the
  // first attach and reused. Parallel uploads race for it, so the PROMISE is
  // memoised, not the id — two racing attaches would otherwise create two
  // projects and orphan half the sources.
  const projectPromise = useRef<Promise<string> | null>(null);
  const topicRef = useRef(topic);
  topicRef.current = topic;
  const languageRef = useRef(language);
  languageRef.current = language;

  useEffect(() => {
    // Read on the client only: useSearchParams would force a Suspense
    // boundary around the whole surface for one prefill.
    const requested = new URLSearchParams(window.location.search).get("lang");
    if (requested && isLanguageCode(requested)) setLanguage(requested);
  }, []);

  // Server truth for what the tier buys (G31). A failure here is not worth an
  // error surface: the card falls back to the client's list price and says so
  // by omitting the rows it cannot honestly fill.
  useEffect(() => {
    let live = true;
    getPricing()
      .then((view) => {
        if (live) setPricing(view.packages);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const refreshBalance = useCallback(() => {
    void withAuth((token) => getBalance(token))
      .then((view) => {
        if (view) setBalance(view.balance);
      })
      .catch(() => undefined);
  }, [withAuth]);

  useEffect(() => {
    if (session) refreshBalance();
  }, [session, refreshBalance]);

  const chosen = packageOf(packageId);
  const tierPricing = pricing?.find((entry) => entry.package === packageId) ?? null;
  const uploading = uploads.some((row) => row.state === "pending");
  const ready = uploads.filter((row) => row.state === "done");
  const failedCount = uploads.filter((row) => row.state === "failed").length;
  const hasTopic = topic.trim().length > 0;
  const blocked = submitBlock({
    hasTopic,
    uploading,
    readyCount: ready.length,
    failedCount,
  });

  const patch = useCallback((key: string, next: Partial<UploadRow>) => {
    setUploads((current) => current.map((row) => (row.key === key ? { ...row, ...next } : row)));
  }, []);

  const ensureProject = useCallback((): Promise<string> => {
    if (!projectPromise.current) {
      projectPromise.current = withAuth((token) =>
        createProject(topicRef.current.trim(), token, languageRef.current),
      )
        .then((project) => {
          if (!project) throw new Error("session_lost");
          setProjectId(project.id);
          return project.id;
        })
        .catch((error: unknown) => {
          projectPromise.current = null;
          throw error;
        });
    }
    return projectPromise.current;
  }, [withAuth]);

  const runUpload = useCallback(
    async (row: UploadRow, pid: string) => {
      patch(row.key, { state: "pending", progress: 0, error: null });
      try {
        const source = await withAuth(async (token) => {
          const presign = await presignUpload(pid, row.file.name, row.file.size, token);
          await uploadToR2WithProgress(presign, row.file, (fraction) =>
            patch(row.key, { progress: fraction }),
          );
          return registerSource(pid, presign.storage_key, row.file.name, token);
        });
        if (!source) return;
        patch(row.key, { state: "done", progress: 1, source, error: null });
      } catch (error) {
        patch(row.key, { state: "failed", error });
      }
    },
    [patch, withAuth],
  );

  const startUploads = useCallback(
    async (files: File[]) => {
      const rows: UploadRow[] = files.map((file) => {
        uploadSeq.current += 1;
        return {
          key: `u-${uploadSeq.current}`,
          file,
          state: "pending",
          progress: 0,
          error: null,
          source: null,
        };
      });
      setUploads((current) => [...current, ...rows]);
      let pid: string;
      try {
        pid = await ensureProject();
      } catch (error) {
        for (const row of rows) patch(row.key, { state: "failed", error });
        return;
      }
      // Parallel, not serial: eight files used to mean eight round trips end
      // to end under one indeterminate header.
      await Promise.allSettled(rows.map((row) => runUpload(row, pid)));
    },
    [ensureProject, patch, runUpload],
  );

  function onAttach(files: File[]) {
    const room = Math.max(0, MAX_SOURCES - uploads.length - held.length);
    const batch = files.slice(0, room);
    if (batch.length === 0) {
      setNote({ text: `Bir loyihaga ${MAX_SOURCES} tagacha manba.`, danger: true });
      return;
    }
    if (!hasTopic) {
      // Held, not dropped: the file the user just chose is the file they meant.
      setHeld((current) => [...current, ...batch]);
      setNote({
        text:
          batch.length === 1
            ? `«${batch[0].name}» saqlandi — mavzuni yozing, keyin darhol yuklanadi.`
            : `${batch.length} ta fayl saqlandi — mavzuni yozing, keyin darhol yuklanadi.`,
      });
      return;
    }
    setNote(null);
    void startUploads(batch);
  }

  // The held files go up the moment a topic exists — the project cannot be
  // created without a title, which is the whole reason they were held.
  useEffect(() => {
    if (!hasTopic || held.length === 0 || !session) return;
    const batch = held;
    setHeld([]);
    setNote(null);
    void startUploads(batch);
  }, [hasTopic, held, session, startUploads]);

  function onRemoveAttachment(index: number) {
    const row = uploads[index];
    if (!row || row.state === "pending") return;
    // The source row stays on the server; dropping it here keeps it out of the
    // enqueue payload, which is what decides what the worker reads.
    setUploads((current) => current.filter((_, i) => i !== index));
  }

  const openQuestions = useCallback(
    async (pid: string) => {
      setInterviewState("loading");
      setInterviewError(null);
      try {
        const view = await withAuth((token) => getInterview(pid, token, languageRef.current));
        if (!view) return;
        setInterview(view);
        setPrepared(prepareQuestions(view));
        setInterviewState(view.questions.length > 0 ? "ready" : "not_ready");
      } catch (error) {
        // 409 sources_not_ready is the DESIGNED first-run answer: sources are
        // only processed during generation, so there is nothing to ask about
        // yet. It is a state, never a failure.
        if (reasonOf(error) === "sources_not_ready") {
          setInterview(null);
          setInterviewState("not_ready");
          return;
        }
        setInterviewError(error);
        setInterviewState("error");
      }
    },
    [withAuth],
  );

  async function onSend() {
    if (!session || busy || stage !== "compose") return;
    if (blocked) {
      setNote({ text: blocked, danger: true });
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      const pid = await ensureProject();
      setStage("questions");
      await openQuestions(pid);
    } catch (error) {
      setEnqueueError(error);
      setStage("compose");
    } finally {
      setBusy(false);
    }
  }

  function toConfirm(next: Record<string, AnswerValue> | undefined, summary: DecisionSummary | null) {
    setAnswers(next && Object.keys(next).length > 0 ? next : undefined);
    setDecided(summary);
    setEnqueueError(null);
    setStage("confirm");
    refreshBalance();
  }

  function onAnswered(collected: ApprovalAnswer[]) {
    toConfirm(buildAnswers(prepared, collected), null);
  }

  async function onConfirm() {
    if (!projectId || enqueuing.current) return;
    enqueuing.current = true;
    setEnqueueError(null);
    try {
      const view = await withAuth((token) =>
        enqueueJob(
          projectId,
          ready.map((row) => ({
            storage_key: row.source?.storage_key ?? "",
            filename: row.file.name,
          })),
          token,
          packageId,
          language,
          topic.trim(),
          answers,
        ),
      );
      if (!view) return;
      router.push(`/projects/${projectId}?job=${view.id}`);
    } catch (error) {
      setEnqueueError(error);
      // The card latches "sent" the moment it fires; remount it so a refused
      // job shows the question again instead of a green confirmation.
      setAttempt((current) => current + 1);
    } finally {
      enqueuing.current = false;
    }
  }

  const attachRow: PromptSource = {
    key: "attach",
    name: "Fayl qo‘shish",
    desc: "Kompyuteringizdan yuklang",
    icon: "clip",
    attach: true,
  };

  const sources: PromptSource[] = [
    attachRow,
    ...ready.map((row) => ({
      key: row.key,
      name: row.file.name,
      desc: `${row.source?.file_type ?? "fayl"} · biriktirilgan`,
      icon: "file" as const,
    })),
  ];

  const pickers: PromptPicker[] = [
    {
      key: "paket",
      label: "Paket",
      value: packageId,
      options: PACKAGES.map((entry) => ({
        key: entry.id,
        name: entry.name,
        tag: soum(pricing?.find((row) => row.package === entry.id)?.price ?? entry.price),
      })),
      onChange: (key) => setPackageId(key as PackageId),
    },
    {
      key: "til",
      label: "Til",
      value: language,
      options: LANGUAGES.map((entry) => ({ key: entry.code, name: entry.name })),
      onChange: (key) => setLanguage(key as LanguageCode),
    },
  ];

  const rows = planRows({
    topic: topic.trim(),
    languageLabel: languageName(language),
    packageLabel: chosen.name,
    sourceCount: ready.length,
    pricing: tierPricing,
    fallbackPrice: chosen.price,
    balance,
    estimatedSlides: interview?.estimated_slide_count ?? null,
    soum,
  });

  function focusComposer() {
    document.querySelector<HTMLTextAreaElement>("[data-promptbar] textarea")?.focus();
  }

  const priceLine = `${chosen.name} · ${soum(tierPricing?.price ?? chosen.price)}`;

  return (
    <AppChrome active="new">
      <div className="new-stage">
        <div className="new-head">
          <h1 className="new-title">Nima yaratamiz?</h1>
          <p className="new-sub">
            Mavzuni yozing va manba biriktiring — Nashr faqat siz bergan dalilga tayanadi.
          </p>
        </div>

        <div className="new-composer">
          <PromptBar
            value={topic}
            onChange={(next) => {
              setTopic(next);
              if (note?.danger) setNote(null);
            }}
            onSend={() => void onSend()}
            placeholder="Mavzu yoki sarlavhani yozing… @ bilan manba qo‘shing"
            tall
            maxLength={200}
            accept={ACCEPTED}
            maxAttachments={MAX_SOURCES}
            attachments={uploads.map((row) => row.file.name)}
            onAttach={onAttach}
            onRemoveAttachment={onRemoveAttachment}
            sources={sources}
            pickers={pickers}
            disabled={stage !== "compose"}
            busy={busy}
          />

          {stage === "compose" && (
            <p className="new-note" data-danger={note?.danger ? "true" : undefined}>
              {note
                ? note.text
                : `${priceLine} · PDF, DOCX, PPTX — kamida bitta manba kerak, ${MAX_SOURCES} tagacha.`}
            </p>
          )}
        </div>

        {uploads.length > 0 && (
          <div className="new-uploads">
            <p className="new-uploads-head">
              {uploading
                ? "Manbalar yuklanmoqda"
                : `${ready.length} ta manba tayyor${failedCount > 0 ? `, ${failedCount} tasi yuklanmadi` : ""}`}
            </p>
            <ul className="new-files">
              {uploads.map((row) => {
                const friendly = row.error ? describeError(row.error) : null;
                return (
                  <li key={row.key} className="new-file" data-state={row.state}>
                    <span className="new-file-head">
                      <span className="new-file-name data-text">{row.file.name}</span>
                      <span className="new-file-meta data-text">{humanSize(row.file.size)}</span>
                    </span>
                    {row.state === "pending" && (
                      <span
                        className="new-file-bar"
                        role="progressbar"
                        aria-valuenow={Math.round(row.progress * 100)}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-label={`${row.file.name} yuklanmoqda`}
                      >
                        <i style={{ width: `${Math.max(3, Math.round(row.progress * 100))}%` }} />
                      </span>
                    )}
                    <span className="new-file-line">
                      {row.state === "pending"
                        ? `${Math.round(row.progress * 100)}%`
                        : row.state === "done"
                          ? `${row.source?.file_type ?? "fayl"} · ro‘yxatdan o‘tdi`
                          : (friendly?.message ?? "Yuklanmadi")}
                    </span>
                    {row.state === "failed" && (
                      <span className="new-file-actions">
                        <button
                          type="button"
                          className="new-file-action"
                          onClick={() => {
                            void ensureProject()
                              .then((pid) => runUpload(row, pid))
                              .catch((error: unknown) =>
                                patch(row.key, { state: "failed", error }),
                              );
                          }}
                        >
                          Qayta urinish
                        </button>
                        <button
                          type="button"
                          className="new-file-action"
                          onClick={() =>
                            setUploads((current) => current.filter((item) => item.key !== row.key))
                          }
                        >
                          Olib tashlash
                        </button>
                      </span>
                    )}
                    {row.state === "failed" && friendly?.detail && (
                      <details className="new-detail">
                        <summary>Texnik tafsilot</summary>
                        <code>{friendly.detail}</code>
                      </details>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {stage === "questions" && (
          <div className="new-step">
            {interviewState === "loading" && (
              <p className="new-step-lead">Manbalaringiz bo‘yicha savollar tayyorlanmoqda…</p>
            )}

            {interviewState === "ready" && interview && (
              <>
                <p className="new-step-lead">
                  Bir necha savol — javoblaringiz taqdimotni aniqroq qiladi. Xohlamasangiz,
                  o‘tkazib yuborishingiz mumkin.
                </p>
                <div className="new-cardwrap">
                  <ApprovalCard
                    questions={prepared.map((item) => item.card)}
                    allowCustom
                    sentLabel="Javoblar qabul qilindi"
                    onSubmitted={onAnswered}
                  />
                </div>
                <div className="new-exits">
                  <Button
                    variant="ghost"
                    onClick={() => toConfirm(undefined, decisionSummary(interview))}
                  >
                    O‘zingiz tanlang
                  </Button>
                  <Button variant="ghost" onClick={() => toConfirm(undefined, null)}>
                    Keyinroq
                  </Button>
                </div>
              </>
            )}

            {interviewState === "not_ready" && (
              <>
                <DecisionPanel summary={decisionSummary(interview)} />
                <div className="new-exits">
                  <Button onClick={() => toConfirm(undefined, decisionSummary(interview))}>
                    Yaxshi, o‘zingiz tanlang
                  </Button>
                </div>
              </>
            )}

            {interviewState === "error" && (
              <>
                <InlineError
                  error={interviewError}
                  onRetry={() => {
                    if (projectId) void openQuestions(projectId);
                  }}
                />
                <div className="new-exits">
                  <Button variant="ghost" onClick={() => toConfirm(undefined, decisionSummary(null))}>
                    Savolsiz davom etish
                  </Button>
                </div>
              </>
            )}

            <button type="button" className="new-cancel" onClick={() => setStage("compose")}>
              Orqaga
            </button>
          </div>
        )}

        {stage === "confirm" && (
          <div className="new-confirm">
            {decided && <DecisionPanel summary={decided} />}
            <ApprovalCard
              key={attempt}
              questions={[
                {
                  q: "Generatsiyani boshlaymizmi?",
                  type: "radio",
                  options: [{ label: "Ha, boshlash", hint: "Odatda 3-6 daqiqa" }],
                },
              ]}
              summary={
                <span className="new-summary">
                  {rows.map((row) => (
                    <span className="new-summary-row" key={row.label}>
                      <span className="new-summary-key">{row.label}</span>
                      <span
                        className={row.mono ? "new-summary-value data-text" : "new-summary-value"}
                      >
                        {row.value}
                      </span>
                    </span>
                  ))}
                  <span className="new-summary-note">{CHARGE_NOTE}</span>
                </span>
              }
              sentLabel="Boshlanmoqda"
              onSubmitted={() => void onConfirm()}
            />
            <button type="button" className="new-cancel" onClick={() => setStage("compose")}>
              Bekor qilish
            </button>
            {enqueueError !== null && (
              <div className="new-errors">
                <InlineError
                  error={enqueueError}
                  money
                  rate
                  onRetry={() => {
                    void onConfirm();
                  }}
                />
              </div>
            )}
          </div>
        )}

        {stage === "compose" && enqueueError !== null && (
          <div className="new-errors">
            <InlineError
              error={enqueueError}
              retryLabel="Qayta urinish"
              onRetry={() => {
                setEnqueueError(null);
                void onSend();
              }}
            />
          </div>
        )}

        {stage === "compose" && (
          <div className="new-templates">
            <button
              type="button"
              className="new-template"
              aria-pressed="true"
              onClick={focusComposer}
            >
              <span className="new-template-icon" aria-hidden>
                <Presentation size={17} strokeWidth={1.75} />
              </span>
              <span className="new-template-name">Taqdimot</span>
              <span className="new-template-line">Manbaga bog‘langan slaydlar, uch formatda.</span>
            </button>
            <div className="new-template" data-soon="true">
              <span className="new-template-icon" aria-hidden>
                <FileText size={17} strokeWidth={1.75} />
              </span>
              <span className="new-template-name">
                Maqola
                <span className="new-template-soon">tez kunda</span>
              </span>
              <span className="new-template-line">Dalillar matritsasi va tekshirilgan iqtiboslar.</span>
            </div>
            <div className="new-template" data-soon="true">
              <span className="new-template-icon" aria-hidden>
                <GraduationCap size={17} strokeWidth={1.75} />
              </span>
              <span className="new-template-name">
                Dissertatsiya
                <span className="new-template-soon">tez kunda</span>
              </span>
              <span className="new-template-line">Uzun shakl, boblar va adabiyotlar ro‘yxati.</span>
            </div>
          </div>
        )}
      </div>
    </AppChrome>
  );
}
