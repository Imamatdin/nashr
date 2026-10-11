"use client";

import { useEffect, useRef } from "react";
import { History, RotateCcw, X } from "lucide-react";
import type { DocumentRevision } from "@/lib/api";
import type { DesignerCopy } from "./presentation-designer-copy";

export function DesignHistory({
  revisions,
  currentRevisionId,
  copy,
  locale,
  error,
  restoring,
  onClose,
  onRestore,
}: {
  revisions: DocumentRevision[] | null;
  currentRevisionId: string;
  copy: DesignerCopy;
  locale: string;
  error: boolean;
  restoring: boolean;
  onClose: () => void;
  onRestore: (revisionId: string) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div
      className="designer-history"
      role="dialog"
      aria-modal="true"
      aria-labelledby="designer-history-title"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      <div className="designer-history-panel">
        <header>
          <div>
            <History size={17} />
            <h2 id="designer-history-title">{copy.history}</h2>
          </div>
          <button ref={closeRef} aria-label={copy.close} onClick={onClose}>
            <X size={17} />
          </button>
        </header>
        {error ? (
          <p role="alert">{copy.historyError}</p>
        ) : revisions === null ? (
          <p>{copy.historyLoading}</p>
        ) : (
          <ol>
            {revisions.map((revision) => {
              const current = revision.id === currentRevisionId;
              return (
                <li key={revision.id}>
                  <div>
                    <strong>
                      {current
                        ? copy.current
                        : new Date(revision.created_at).toLocaleString(locale)}
                    </strong>
                    <small>{revision.content_sha256.slice(0, 8)}</small>
                  </div>
                  {!current && (
                    <button
                      disabled={restoring}
                      onClick={() => onRestore(revision.id)}
                    >
                      <RotateCcw size={14} />
                      {restoring ? copy.restoring : copy.restore}
                    </button>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
