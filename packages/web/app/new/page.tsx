"use client";

// The creation surface. One prompt box carries the whole flow: the topic is
// the prompt, sources are attachments on it, tier and language are pickers
// inside it, and the price-bearing confirm is an approval card underneath.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, GraduationCap, Presentation } from "lucide-react";
import { AppChrome } from "@/components/chrome";
import { ApprovalCard, PromptBar, ToolChips } from "@/components/bui";
import type { PromptPicker, PromptSource, ToolRow } from "@/components/bui";
import { ErrorState } from "@/components/ui";
import {
  ApiError,
  type SourceView,
  createProject,
  enqueueJob,
  presignUpload,
  registerSource,
  uploadToR2,
} from "@/lib/api";
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
import { type AppSession, loadSession } from "@/lib/session";

import "./new.css";

const ACCEPTED = ".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv";
const MAX_SOURCES = 10;
const NETWORK_ERROR = "Tarmoqda uzilish — qayta urinib ko‘ring";

const COMMANDS = [
  { key: "manba", name: "/manba", desc: "Manba biriktirish" },
  { key: "til", name: "/til", desc: "Chiqish tilini tanlash" },
  { key: "paket", name: "/paket", desc: "Paketni tanlash" },
];

interface UploadRow {
  key: string;
  filename: string;
  state: "pending" | "done" | "failed";
  note: string;
}

type EnqueueFailure =
  | { kind: "credit"; balance: number; required: number }
  | { kind: "limit" }
  | { kind: "other"; message: string };

// The API answers 402 with a detail object, which the client stringifies (a
// non-string detail would otherwise ride into React children and crash).
function readShortfall(error: ApiError): { balance: number; required: number } | null {
  try {
    const parsed: unknown = JSON.parse(error.reason);
    if (typeof parsed !== "object" || parsed === null) return null;
    const candidate = parsed as Record<string, unknown>;
    if (typeof candidate.balance !== "number" || typeof candidate.required !== "number") {
      return null;
    }
    return { balance: candidate.balance, required: candidate.required };
  } catch {
    return null;
  }
}

function toEnqueueFailure(error: unknown): EnqueueFailure {
  if (error instanceof ApiError) {
    if (error.status === 402) {
      const shortfall = readShortfall(error);
      if (shortfall) return { kind: "credit", ...shortfall };
    }
    if (error.status === 429) return { kind: "limit" };
    return { kind: "other", message: error.reason };
  }
  return { kind: "other", message: NETWORK_ERROR };
}

function reasonOf(error: unknown): string {
  return error instanceof ApiError ? error.reason : "tarmoq xatosi";
}

function SummaryRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <span className="new-summary-row">
      <span className="new-summary-key">{label}</span>
      <span className={mono ? "new-summary-value data-text" : "new-summary-value"}>{value}</span>
    </span>
  );
}

export default function NewProjectPage() {
  const router = useRouter();
  const [session, setSession] = useState<AppSession | null>(null);

  const [topic, setTopic] = useState("");
  const [language, setLanguage] = useState<LanguageCode>(DEFAULT_LANGUAGE);
  const [packageId, setPackageId] = useState<PackageId>(DEFAULT_PACKAGE);

  const [projectId, setProjectId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; danger?: boolean } | null>(null);

  const [uploads, setUploads] = useState<UploadRow[]>([]);
  const [registered, setRegistered] = useState<SourceView[]>([]);

  const [confirming, setConfirming] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [enqueueError, setEnqueueError] = useState<EnqueueFailure | null>(null);
  const enqueuing = useRef(false);
  const uploadSeq = useRef(0);

  useEffect(() => {
    const active = loadSession();
    if (!active) {
      const here = window.location.pathname + window.location.search;
      router.replace(`/login?returnTo=${encodeURIComponent(here)}`);
      return;
    }
    setSession(active);
    // Read on the client only: useSearchParams would force a Suspense
    // boundary around the whole surface for one prefill.
    const requested = new URLSearchParams(window.location.search).get("lang");
    if (requested && isLanguageCode(requested)) setLanguage(requested);
  }, [router]);

  const chosen = packageOf(packageId);
  const uploading = uploads.some((row) => row.state === "pending");
  const allFailed = uploads.length > 0 && registered.length === 0 && !uploading;
  const hasTopic = topic.trim().length > 0;

  const patch = useCallback((key: string, next: Partial<UploadRow>) => {
    setUploads((current) => current.map((row) => (row.key === key ? { ...row, ...next } : row)));
  }, []);

  // The project is the parent every source hangs off, so it is created at the
  // first attach and reused by the submit; a second call would orphan the
  // sources already registered against the first id.
  const ensureProject = useCallback(
    async (active: AppSession): Promise<string> => {
      if (projectId) return projectId;
      const project = await createProject(topic.trim(), active.accessToken, language);
      setProjectId(project.id);
      return project.id;
    },
    [projectId, topic, language],
  );

  async function onAttach(files: File[]) {
    if (!session) return;
    if (!hasTopic) {
      setNote({ text: "Avval mavzuni yozing — keyin manba biriktirasiz.", danger: true });
      return;
    }
    const room = Math.max(0, MAX_SOURCES - uploads.length);
    const batch = files.slice(0, room);
    if (batch.length === 0) {
      setNote({ text: `Bir loyihaga ${MAX_SOURCES} tagacha manba.`, danger: true });
      return;
    }
    const rows: UploadRow[] = batch.map((file) => {
      uploadSeq.current += 1;
      return {
        key: `u-${uploadSeq.current}`,
        filename: file.name,
        state: "pending",
        note: "Yuklanmoqda…",
      };
    });
    setUploads((current) => [...current, ...rows]);
    setNote(null);
    setBusy(true);

    let pid: string;
    try {
      pid = await ensureProject(session);
    } catch (error) {
      const text = reasonOf(error);
      for (const row of rows) patch(row.key, { state: "failed", note: text });
      setNote({ text: "Loyiha yaratilmadi — qayta urinib ko‘ring", danger: true });
      setBusy(false);
      return;
    }

    for (const [index, file] of batch.entries()) {
      const row = rows[index];
      try {
        const presign = await presignUpload(pid, file.name, file.size, session.accessToken);
        await uploadToR2(presign, file);
        const source = await registerSource(
          pid,
          presign.storage_key,
          file.name,
          session.accessToken,
        );
        setRegistered((current) => [...current, source]);
        patch(row.key, { state: "done", note: `${source.file_type} · ro‘yxatdan o‘tdi` });
      } catch (error) {
        patch(row.key, { state: "failed", note: `Yuklanmadi — ${reasonOf(error)}` });
      }
    }
    setBusy(false);
  }

  function onRemoveAttachment(index: number) {
    const row = uploads[index];
    if (!row || row.state === "pending") return;
    setUploads((current) => current.filter((_, i) => i !== index));
    // The source row stays on the server; dropping it here simply keeps it out
    // of the enqueue payload, which is what decides what the worker reads.
    setRegistered((current) => current.filter((source) => source.filename !== row.filename));
  }

  async function onSend() {
    if (!session || busy || confirming) return;
    if (!hasTopic) {
      setNote({ text: "Avval mavzuni yozing.", danger: true });
      return;
    }
    if (uploading) {
      setNote({ text: "Manbalar hali yuklanmoqda — bir lahza kuting.", danger: true });
      return;
    }
    if (allFailed) {
      setNote({
        text: "Hech bir manba ro‘yxatdan o‘tmadi — qayta biriktiring yoki chiplarni olib tashlang.",
        danger: true,
      });
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      await ensureProject(session);
      setEnqueueError(null);
      setConfirming(true);
    } catch (error) {
      setNote({
        text: error instanceof ApiError ? error.reason : NETWORK_ERROR,
        danger: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    if (!session || !projectId || enqueuing.current) return;
    enqueuing.current = true;
    setEnqueueError(null);
    try {
      const view = await enqueueJob(
        projectId,
        registered.map((source) => ({
          storage_key: source.storage_key,
          filename: source.filename,
        })),
        session.accessToken,
        packageId,
        language,
      );
      router.push(`/projects/${projectId}?job=${view.id}`);
    } catch (error) {
      setEnqueueError(toEnqueueFailure(error));
      // The card latches "sent" the moment it fires; remount it so a refused
      // job shows the question again instead of a green confirmation.
      setAttempt((current) => current + 1);
      enqueuing.current = false;
    }
  }

  const attachRow: PromptSource = {
    key: "attach",
    name: "Fayl qo‘shish",
    desc: hasTopic ? "Kompyuteringizdan yuklang" : "Avval mavzuni yozing",
    icon: "clip",
    attach: true,
  };

  const sources: PromptSource[] = [
    attachRow,
    ...registered.map((source) => ({
      key: source.id,
      name: source.filename,
      desc: `${source.file_type} · biriktirilgan`,
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
        tag: soum(entry.price),
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

  const toolRows: ToolRow[] = uploads.map((row) => ({
    key: row.key,
    icon: "file",
    label: "Manba",
    chip: row.filename,
    mono: true,
    state: row.state,
    detail: [{ text: row.note, ...(row.state === "failed" ? { tone: "error" as const } : {}) }],
  }));

  const doneCount = uploads.filter((row) => row.state === "done").length;

  function focusComposer() {
    document.querySelector<HTMLTextAreaElement>("[data-promptbar] textarea")?.focus();
  }

  return (
    <AppChrome active="new">
      <div className="new-stage">
        <div className="new-head">
          <h1 className="new-title">Nima yaratamiz?</h1>
          <p className="new-sub">
            Mavzuni yozing yoki manba biriktiring — Nashr faqat siz bergan dalilga tayanadi.
          </p>
        </div>

        <div className="new-composer">
          <PromptBar
            value={topic}
            onChange={(next) => {
              setTopic(next);
              if (note) setNote(null);
            }}
            onSend={() => void onSend()}
            placeholder="Mavzu yoki sarlavhani yozing… @ bilan manba qo‘shing"
            tall
            maxLength={200}
            accept={ACCEPTED}
            maxAttachments={MAX_SOURCES}
            attachments={uploads.map((row) => row.filename)}
            onAttach={(files) => void onAttach(files)}
            onRemoveAttachment={onRemoveAttachment}
            sources={sources}
            commands={COMMANDS}
            onCommand={() => undefined}
            pickers={pickers}
            disabled={confirming}
            busy={busy}
          />

          {!confirming && (
            <p className="new-note" data-danger={note?.danger ? "true" : undefined}>
              {note
                ? note.text
                : uploads.length > 0
                  ? `${chosen.name} · ${soum(chosen.price)}`
                  : `PDF, DOCX, PPTX — ${MAX_SOURCES} tagacha. Manbasiz ham boshlash mumkin.`}
            </p>
          )}
        </div>

        {uploads.length > 0 && (
          <div className="new-uploads">
            <ToolChips
              header={uploading ? "Manbalar yuklanmoqda" : `${doneCount} ta manba tayyor`}
              rows={toolRows}
            />
          </div>
        )}

        {confirming ? (
          <div className="new-confirm">
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
                  <SummaryRow label="Mavzu" value={topic.trim()} />
                  <SummaryRow label="Til" value={languageName(language)} />
                  <SummaryRow label="Paket" value={chosen.name} />
                  <SummaryRow label="Narx" value={soum(chosen.price)} mono />
                  <SummaryRow label="Manbalar" value={`${registered.length} ta`} mono />
                </span>
              }
              sentLabel="Boshlanmoqda"
              onSubmitted={() => void onConfirm()}
            />
            <button type="button" className="new-cancel" onClick={() => setConfirming(false)}>
              Bekor qilish
            </button>
            {enqueueError && (
              <div className="new-errors">
                {enqueueError.kind === "credit" && (
                  <ErrorState
                    title="Kredit yetarli emas"
                    message={`Hisobingizda ${soum(enqueueError.balance)}, bu paket uchun ${soum(
                      enqueueError.required,
                    )} kerak. To‘lov Telegram bot orqali amalga oshiriladi.`}
                  />
                )}
                {enqueueError.kind === "limit" && (
                  <ErrorState
                    title="Kunlik limit"
                    message="Kunlik limitga yetdingiz — ertaga qayta urinib ko‘ring."
                  />
                )}
                {enqueueError.kind === "other" && (
                  <ErrorState
                    title="Generatsiya boshlanmadi"
                    message={enqueueError.message}
                    onRetry={() => void onConfirm()}
                  />
                )}
              </div>
            )}
          </div>
        ) : (
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
