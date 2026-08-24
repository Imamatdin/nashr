import { describe, expect, it } from "vitest";
import type { LedgerEntryView } from "./api";
import { describeLedgerEntry, ledgerDate, rewardCopy, signedSoum } from "./ledger";

function row(over: Partial<LedgerEntryView>): LedgerEntryView {
  return {
    id: "row-1",
    amount: 5000,
    action: "grant_free",
    reason: "learning_reward",
    project_id: null,
    generation_job_id: null,
    created_at: "2026-08-24T09:15:00+00:00",
    ...over,
  };
}

describe("signed amounts", () => {
  it("leads with the sign so a spend and a refund never look alike", () => {
    expect(signedSoum(5000)).toBe("+5 000 so‘m");
    expect(signedSoum(-10000)).toBe("−10 000 so‘m");
    expect(signedSoum(0)).toBe("+0 so‘m");
  });
});

describe("dates", () => {
  it("files a row as dd.mm.yyyy", () => {
    expect(ledgerDate("2026-08-24T09:15:00+00:00")).toMatch(/^\d{2}\.\d{2}\.2026$/);
  });

  it("never renders NaN or the raw string", () => {
    expect(ledgerDate(null)).toBe("—");
    expect(ledgerDate("not-a-date")).toBe("—");
  });
});

describe("G24 — the learning reward is finally said out loud", () => {
  it("leads with the benefit and mentions the credit second (source_upload)", () => {
    const copy = rewardCopy(row({ reason: "source_upload", amount: 5000 }));
    const benefit = copy.indexOf("dalil bazasini");
    const credit = copy.indexOf("bepul kredit");
    expect(benefit).toBeGreaterThanOrEqual(0);
    expect(credit).toBeGreaterThan(benefit);
    expect(copy).toContain("5 000 so‘m");
  });

  // The shape production actually stores: `_insert` overwrites the detailed
  // reason with `_ACTION_TO_REASON[action]`, so a granted source-upload credit
  // comes back as "learning_reward" and must still read as a reward.
  it("still reads as a reward for the persisted learning_reward shape", () => {
    const described = describeLedgerEntry(row({ reason: "learning_reward", amount: 5000 }));
    expect(described.tone).toBe("reward");
    expect(described.label).toBe("O‘rganish mukofoti");
    expect(described.note).not.toBeNull();
    expect(described.note?.indexOf("bepul kredit")).toBeGreaterThan(0);
  });

  it("states the row's own amount, not a hardcoded free-credit value", () => {
    expect(rewardCopy(row({ reason: "source_upload", amount: 3000 }))).toContain("3 000 so‘m");
  });
});

describe("deductions", () => {
  it("renders a negative amount as a spend with a link to its project", () => {
    const described = describeLedgerEntry(
      row({
        action: "deduct_presentation",
        reason: "presentation_generation",
        amount: -10000,
        project_id: "p-42",
      }),
    );
    expect(described.label).toBe("Taqdimot yaratildi");
    expect(described.tone).toBe("spend");
    expect(described.amount).toBe("−10 000 so‘m");
    expect(described.href).toBe("/projects/p-42");
    expect(described.note).toBeNull();
  });
});

describe("refunds read as refunds", () => {
  it("is positive, labelled as returned, and links to the job's project", () => {
    const described = describeLedgerEntry(
      row({
        action: "refund",
        reason: "refund",
        amount: 10000,
        project_id: "p-42",
        generation_job_id: "job-7",
      }),
    );
    expect(described.tone).toBe("refund");
    expect(described.label).toContain("qaytarildi");
    expect(described.amount).toBe("+10 000 so‘m");
    expect(described.href).toBe("/projects/p-42");
    expect(described.note).toContain("qaytarildi");
  });
});

describe("an action this build has never seen", () => {
  it("still produces human copy instead of blanking the row", () => {
    const described = describeLedgerEntry(
      // Cast at the wire boundary: the ledger is append-only and the API may
      // grow an action before this client does.
      row({ action: "chargeback" as LedgerEntryView["action"], amount: -1000 }),
    );
    expect(described.label).toBe("Hisob amaliyoti");
    expect(described.label).not.toContain("chargeback");
    expect(described.tone).toBe("neutral");
    expect(described.amount).toBe("−1 000 so‘m");
  });
});
