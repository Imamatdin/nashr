"use client";

// Stored proposals: AI or regeneration output that lost the race to the head
// (ADR 0001). Accepting replaces the head the user is LOOKING AT, so the user
// first sees both diffs — what the AI changed, and what accepting changes now
// (including their own later edits it would replace) — and the accept carries
// the head that diff was computed against. A moved head refreshes the diff.

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  acceptProposal,
  getProposalDiff,
  listProposals,
  rejectProposal,
  type DiffEntry,
  type ProposalDiffView,
  type ProposalView,
  type RevisionDiff,
} from "@/lib/api";
import { useAppSession } from "@/lib/use-session";
import type { DESIGNER_COPY } from "./presentation-designer-copy";

type Copy = (typeof DESIGNER_COPY)["en"];

const CHANGE_LABEL: Record<DiffEntry["change"], keyof Copy> = {
  added: "changeAdded",
  removed: "changeRemoved",
  changed: "changeChanged",
  moved: "changeMoved",
};

function DiffList({ diff, copy }: { diff: RevisionDiff; copy: Copy }) {
  if (diff.entries.length === 0)
    return <p className="proposal-empty">{copy.noChanges}</p>;
  return (
    <ul className="proposal-diff">
      {diff.entries.map((entry) => (
        <li key={`${entry.change}-${entry.item_id}`} data-change={entry.change}>
          <span className="proposal-change">{copy[CHANGE_LABEL[entry.change]]}</span>
          <span>{entry.label || entry.item_id}</span>
        </li>
      ))}
    </ul>
  );
}

/** Entries that change slides the AI did not touch: the user's own later edits. */
function revertsUserEdits(view: ProposalDiffView): boolean {
  const touched = new Set(view.ai_changes.entries.map((entry) => entry.item_id));
  return view.accept_changes.entries.some((entry) => !touched.has(entry.item_id));
}

export function ProposalsPanel({
  projectId,
  copy,
  onAccepted,
}: {
  projectId: string;
  copy: Copy;
  onAccepted: () => void;
}) {
  const { withAuth } = useAppSession();
  const [proposals, setProposals] = useState<ProposalView[]>([]);
  const [open, setOpen] = useState<ProposalDiffView | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await withAuth((token) => listProposals(projectId, token));
      if (result) setProposals(result.proposals);
    } catch {
      // A missing proposals list must never cost the user the designer.
    }
  }, [projectId, withAuth]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function review(proposalId: string) {
    setMessage(null);
    const diff = await withAuth((token) => getProposalDiff(projectId, proposalId, token)).catch(
      () => null,
    );
    setOpen(diff ?? null);
  }

  async function accept() {
    if (!open || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      await withAuth((token) =>
        acceptProposal(
          projectId,
          open.proposal.id,
          open.head_revision_id,
          crypto.randomUUID(),
          token,
        ),
      );
      setOpen(null);
      await refresh();
      onAccepted();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && error.reason.includes("stale_revision")) {
        // The head moved after the diff was shown: show the new comparison.
        setMessage(copy.proposalMoved);
        await review(open.proposal.id);
      } else if (error instanceof ApiError && error.reason.includes("proposal_schema_mismatch")) {
        setMessage(copy.schemaMismatch);
      } else {
        setMessage(copy.proposalError);
      }
    } finally {
      setBusy(false);
    }
  }

  async function reject(proposalId: string) {
    if (busy) return;
    setBusy(true);
    try {
      await withAuth((token) => rejectProposal(projectId, proposalId, token));
      setOpen(null);
      await refresh();
    } catch {
      setMessage(copy.proposalError);
    } finally {
      setBusy(false);
    }
  }

  if (proposals.length === 0) return null;
  return (
    <section className="proposals" aria-label={copy.proposals}>
      <header>
        <strong>{copy.proposals}</strong>
        <p>{copy.proposalIntro}</p>
      </header>
      <ul className="proposal-list">
        {proposals.map((proposal) => (
          <li key={proposal.id}>
            <time dateTime={proposal.created_at}>
              {new Date(proposal.created_at).toLocaleString()}
            </time>
            <button onClick={() => void review(proposal.id)}>{copy.review}</button>
            <button onClick={() => void reject(proposal.id)} disabled={busy}>
              {copy.reject}
            </button>
          </li>
        ))}
      </ul>
      {message && (
        <p className="proposal-message" role="status">
          {message}
        </p>
      )}
      {open && (
        <div className="proposal-review">
          <h4>{copy.aiChanged}</h4>
          <DiffList diff={open.ai_changes} copy={copy} />
          <h4>{copy.acceptChanges}</h4>
          <DiffList diff={open.accept_changes} copy={copy} />
          {revertsUserEdits(open) && <p className="proposal-warning">{copy.revertsYours}</p>}
          {!open.schema_matches_head && (
            <p className="proposal-warning">{copy.schemaMismatch}</p>
          )}
          <div className="proposal-actions">
            <button
              onClick={() => void accept()}
              disabled={busy || !open.schema_matches_head}
            >
              {busy ? copy.accepting : copy.accept}
            </button>
            <button onClick={() => setOpen(null)}>{copy.close}</button>
          </div>
        </div>
      )}
    </section>
  );
}
