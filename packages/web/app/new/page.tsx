"use client";

// The start-a-generation flow (P3.6). One page, three progressive steps —
// this is where the Telegram bot's button lands, so it is built for a 390px
// webview first: single column, one action per step, nothing that scrolls
// sideways. The gilded moment of the view is the final "Taqdimotni boshlash".

import { type CSSProperties, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AppChrome } from "@/components/chrome";
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
import { type AppSession, loadSession } from "@/lib/session";

const ACCEPTED = ".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv";
const MAX_SOURCES = 10;

const LANGUAGES = [
  { code: "uz", name: "O'zbekcha" },
  { code: "kaa", name: "Qaraqalpaqsha" },
  { code: "ru", name: "Русский" },
  { code: "en", name: "English" },
] as const;

type LanguageCode = (typeof LANGUAGES)[number]["code"];

const PACKAGES = [
  {
    id: "presentation_basic",
    name: "Oddiy",
    price: 5000,
    desc: "AI rasmsiz — toza tipografik dizayn",
  },
  {
    id: "presentation_standard",
    name: "Standart",
    price: 10000,
    desc: "Muqova + asosiy vizual (2 AI rasm)",
  },
  {
    id: "presentation_premium",
    name: "Premium",
    price: 15000,
    desc: "5 tagacha AI rasm",
  },
] as const;

type PackageId = (typeof PACKAGES)[number]["id"];

const LABEL: CSSProperties = {
  display: "block",
  fontSize: "var(--text-sm)",
  fontWeight: 600,
  marginBottom: "var(--sp-2)",
};

const GROUP: CSSProperties = {
  border: 0,
  padding: 0,
  margin: "0 0 var(--sp-5) 0",
  minInlineSize: 0,
};

const NOTE_LINE: CSSProperties = {
  minHeight: "1.35rem",
  margin: "var(--sp-3) 0 0",
  fontSize: "var(--text-sm)",
};

function soum(amount: number): string {
  return `${amount.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ")} so'm`;
}

function isLanguageCode(value: string): value is LanguageCode {
  return LANGUAGES.some((entry) => entry.code === value);
}

function languageName(code: LanguageCode): string {
  return LANGUAGES.find((entry) => entry.code === code)?.name ?? code;
}

function packageOf(id: PackageId): (typeof PACKAGES)[number] {
  return PACKAGES.find((entry) => entry.id === id) ?? PACKAGES[1];
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
  return { kind: "other", message: "Tarmoqda uzilish — qayta urinib ko'ring" };
}

function SummaryRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: "var(--sp-4)",
        padding: "0.55rem 0",
        borderTop: "1px solid var(--rule)",
      }}
    >
      <span style={{ color: "var(--muted-ink)", fontSize: "var(--text-sm)" }}>{label}</span>
      <span
        style={{
          textAlign: "right",
          minWidth: 0,
          fontFamily: mono ? "var(--font-mono)" : undefined,
          fontSize: mono ? "var(--text-sm)" : undefined,
        }}
      >
        {value}
      </span>
    </div>
  );
}

export default function NewProjectPage() {
  const router = useRouter();
  const [session, setSession] = useState<AppSession | null>(null);

  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState<LanguageCode>("uz");
  const [packageId, setPackageId] = useState<PackageId>("presentation_standard");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);

  const [sources, setSources] = useState<SourceView[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadNote, setUploadNote] = useState<{ text: string; danger?: boolean } | null>(null);
  const [sourcesConfirmed, setSourcesConfirmed] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const [enqueueing, setEnqueueing] = useState(false);
  const [enqueueError, setEnqueueError] = useState<EnqueueFailure | null>(null);

  useEffect(() => {
    const active = loadSession();
    if (!active) {
      const here = window.location.pathname + window.location.search;
      router.replace(`/login?returnTo=${encodeURIComponent(here)}`);
      return;
    }
    setSession(active);
    // Read on the client only: useSearchParams would force a Suspense
    // boundary around the whole flow for one prefill.
    const requested = new URLSearchParams(window.location.search).get("lang");
    if (requested && isLanguageCode(requested)) setLanguage(requested);
  }, [router]);

  const stage = projectId === null ? 1 : sourcesConfirmed ? 3 : 2;
  const chosenPackage = packageOf(packageId);
  const full = sources.length >= MAX_SOURCES;

  function stepClass(step: number): string {
    if (stage > step) return "flow-step flow-step-done";
    if (stage < step) return "flow-step flow-step-locked";
    return "flow-step";
  }

  async function onCreate() {
    if (!session || creating || !title.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const project = await createProject(title.trim(), session.accessToken, language);
      setProjectId(project.id);
    } catch (error) {
      setCreateError(
        error instanceof ApiError ? error.reason : "Tarmoqda uzilish — qayta urinib ko'ring",
      );
    } finally {
      setCreating(false);
    }
  }

  async function onUpload() {
    if (!session || !projectId || uploading) return;
    const input = fileInput.current;
    const chosen = input?.files ? Array.from(input.files) : [];
    if (chosen.length === 0) {
      setUploadNote({ text: "Avval fayl tanlang", danger: true });
      return;
    }
    const batch = chosen.slice(0, MAX_SOURCES - sources.length);
    setUploading(true);
    setUploadNote(null);
    const failed: string[] = [];
    let reason = "";
    for (const file of batch) {
      try {
        const presign = await presignUpload(
          projectId,
          file.name,
          file.size,
          session.accessToken,
        );
        await uploadToR2(presign, file);
        const registered = await registerSource(
          projectId,
          presign.storage_key,
          file.name,
          session.accessToken,
        );
        setSources((current) => [...current, registered]);
      } catch (error) {
        failed.push(file.name);
        if (!reason) reason = error instanceof ApiError ? error.reason : "tarmoq xatosi";
      }
    }
    if (input) input.value = "";
    setUploading(false);
    if (failed.length > 0) {
      setUploadNote({ text: `${failed.join(", ")} yuklanmadi — ${reason}`, danger: true });
    } else if (batch.length < chosen.length) {
      setUploadNote({
        text: `Bir loyihaga ${MAX_SOURCES} tagacha manba — ortiqchasi yuklanmadi`,
        danger: true,
      });
    }
  }

  async function onEnqueue() {
    if (!session || !projectId || enqueueing) return;
    setEnqueueing(true);
    setEnqueueError(null);
    try {
      const view = await enqueueJob(
        projectId,
        sources.map((source) => ({
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
      setEnqueueing(false);
    }
  }

  return (
    <AppChrome active="new">
      <div className="page-head">
        <h1 className="page-title">Yangi taqdimot</h1>
        <p className="page-sub">
          Uch qadam: loyihani nomlang, manbalarni yuklang, generatsiyani boshlang. Taqdimot
          faqat siz yuklagan hujjatlardagi faktlarga tayanadi.
        </p>
      </div>

      <section className={stepClass(1)}>
        <div className="flow-step-head">
          <span className="folio">I</span>
          <h2>Loyiha</h2>
        </div>

        {stage === 1 ? (
          <>
            <div style={{ marginBottom: "var(--sp-5)" }}>
              <label htmlFor="title" style={LABEL}>
                Mavzu yoki sarlavha
              </label>
              <input
                id="title"
                name="title"
                className="input"
                type="text"
                autoComplete="off"
                maxLength={200}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Masalan, «Yoritish davri va uning merosi»"
              />
            </div>

            <fieldset style={GROUP}>
              <legend style={LABEL}>Til</legend>
              <div className="choice-grid">
                {LANGUAGES.map((entry) => (
                  <label key={entry.code} className="choice" htmlFor={`language-${entry.code}`}>
                    <input
                      id={`language-${entry.code}`}
                      name="language"
                      type="radio"
                      autoComplete="off"
                      value={entry.code}
                      checked={language === entry.code}
                      onChange={() => setLanguage(entry.code)}
                    />
                    <span className="choice-name">{entry.name}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset style={GROUP}>
              <legend style={LABEL}>Paket</legend>
              <div className="choice-grid">
                {PACKAGES.map((entry) => (
                  <label key={entry.id} className="choice" htmlFor={`package-${entry.id}`}>
                    <input
                      id={`package-${entry.id}`}
                      name="package"
                      type="radio"
                      autoComplete="off"
                      value={entry.id}
                      checked={packageId === entry.id}
                      onChange={() => setPackageId(entry.id)}
                    />
                    <span className="choice-name">{entry.name}</span>
                    <span className="choice-desc">{entry.desc}</span>
                    <span className="choice-price">{soum(entry.price)}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void onCreate()}
              disabled={!session || creating || !title.trim()}
            >
              {creating ? "Yaratilmoqda…" : "Loyihani boshlash"}
            </button>

            {createError && (
              <div style={{ marginTop: "var(--sp-4)" }}>
                <ErrorState
                  title="Loyiha yaratilmadi"
                  message={createError}
                  onRetry={() => void onCreate()}
                />
              </div>
            )}
          </>
        ) : (
          <p style={{ margin: 0, color: "var(--muted-ink)", fontSize: "var(--text-sm)" }}>
            {title} · {languageName(language)} · {chosenPackage.name}
          </p>
        )}
      </section>

      <section className={stepClass(2)}>
        <div className="flow-step-head">
          <span className="folio">II</span>
          <h2>Manbalar</h2>
        </div>

        {sources.length === 0 ? (
          <p style={{ color: "var(--muted-ink)", fontSize: "var(--text-sm)", margin: 0 }}>
            Manbasiz slayd yozilmaydi — har bir da'vo siz yuklagan hujjatga bog'lanadi. PDF,
            DOCX yoki PPTX yuklang.
          </p>
        ) : (
          <div>
            {sources.map((source) => (
              <div key={source.id} className="source-row">
                <span className="file-chip">{source.file_type}</span>
                <span className="source-name">{source.filename}</span>
              </div>
            ))}
          </div>
        )}

        {stage === 2 && (
          <>
            <div className="field-row" style={{ marginTop: "var(--sp-4)", flexWrap: "wrap" }}>
              <input
                ref={fileInput}
                id="sources"
                name="sources"
                className="input"
                type="file"
                autoComplete="off"
                accept={ACCEPTED}
                multiple
                disabled={uploading || full}
              />
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => void onUpload()}
                disabled={uploading || full}
              >
                {uploading ? "Yuklanmoqda…" : "Yuklash"}
              </button>
            </div>

            <p
              style={{
                ...NOTE_LINE,
                color: uploadNote?.danger ? "var(--danger)" : "var(--muted-ink)",
              }}
            >
              {uploading
                ? "Fayllar navbat bilan yuklanmoqda…"
                : (uploadNote?.text ?? `${sources.length} / ${MAX_SOURCES} manba`)}
            </p>

            <button
              type="button"
              className="btn btn-primary"
              style={{ marginTop: "var(--sp-4)" }}
              onClick={() => setSourcesConfirmed(true)}
              disabled={sources.length === 0 || uploading}
            >
              Davom etish
            </button>
          </>
        )}
      </section>

      <section className={stepClass(3)}>
        <div className="flow-step-head">
          <span className="folio">III</span>
          <h2>Tasdiqlash</h2>
        </div>

        <div className="card" style={{ marginBottom: "var(--sp-5)" }}>
          <SummaryRow label="Mavzu" value={title || "—"} />
          <SummaryRow label="Til" value={languageName(language)} />
          <SummaryRow label="Paket" value={chosenPackage.name} />
          <SummaryRow label="Narx" value={soum(chosenPackage.price)} mono />
          <SummaryRow label="Manbalar" value={`${sources.length} ta manba`} />
        </div>

        <button
          type="button"
          className="btn btn-lg"
          style={{ background: "var(--gold)", color: "var(--siyoh)", borderColor: "transparent" }}
          onClick={() => void onEnqueue()}
          disabled={stage !== 3 || enqueueing}
        >
          {enqueueing ? "Boshlanmoqda…" : "Taqdimotni boshlash"}
        </button>

        <p style={{ ...NOTE_LINE, color: "var(--muted-ink)" }}>
          Odatda 3–6 daqiqa. Jarayonni loyiha sahifasida kuzatasiz.
        </p>

        {enqueueError?.kind === "credit" && (
          <ErrorState
            title="Kredit yetarli emas"
            message={`Hisobingizda ${soum(enqueueError.balance)}, bu paket uchun ${soum(
              enqueueError.required,
            )} kerak. To'lov Telegram bot orqali amalga oshiriladi.`}
          />
        )}
        {enqueueError?.kind === "limit" && (
          <ErrorState
            title="Kunlik limit"
            message="Kunlik limitga yetdingiz — ertaga qayta urinib ko'ring."
          />
        )}
        {enqueueError?.kind === "other" && (
          <ErrorState
            title="Generatsiya boshlanmadi"
            message={enqueueError.message}
            onRetry={() => void onEnqueue()}
          />
        )}
      </section>
    </AppChrome>
  );
}
