#!/usr/bin/env bash
# P1 gate evidence: a real curl transcript against every route Session W added
# or changed, success AND failure, over the stub-backed app
# (scripts/wire_stub_api.py). Writes review/wire_p1_curl.txt.
#
#   bash scripts/wire_p1_curl.sh
#
# The bearer token is minted by the stub with a throwaway secret and is printed
# in the transcript on purpose: it signs nothing that exists outside this
# process. No real key, project or credit is involved.

set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8099}"
BASE="http://127.0.0.1:${PORT}"
OUT="review/wire_p1_curl.txt"

BANNER="$(python scripts/wire_stub_api.py --banner-only)"
read_field() { python -c "import json,sys;print(json.loads(sys.argv[1])[sys.argv[2]])" "$BANNER" "$1"; }

TOKEN="$(read_field bearer)"
EXPIRED="$(read_field expired_bearer)"
P_READY="$(read_field project_ready)"
P_FAILED="$(read_field project_failed)"
P_EMPTY="$(read_field project_empty)"
P_FOREIGN="$(read_field project_foreign)"
J_DONE="$(read_field job_completed)"
J_FAILED="$(read_field job_failed)"
SHARE="$(read_field share_token)"
SRC_KEY="$(read_field source_key)"

python scripts/wire_stub_api.py --port "$PORT" >/dev/null 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null' EXIT

for _ in $(seq 1 40); do
  curl -sf "${BASE}/health" >/dev/null 2>&1 && break
  sleep 0.25
done

mkdir -p review
: > "$OUT"

say() { printf '%s\n' "$*" >> "$OUT"; }

hit() { # hit <label> <curl args...>
  local label="$1"; shift
  say ""
  say "=============================================================================="
  say "# ${label}"
  # The bearer is redacted in the echoed command: it is a throwaway token,
  # but a transcript that habitually prints credentials teaches the wrong habit.
  say "\$ curl $(printf '%s ' "$@" | sed -E "s/Bearer [A-Za-z0-9._-]+/Bearer <TOKEN>/g")"
  say "------------------------------------------------------------------------------"
  # -w prints the status on its own final line so the transcript shows the code
  # even when the body is empty.
  curl -s -o - -w '\n<< HTTP %{http_code} >>\n' "$@" >> "$OUT" 2>&1
}

AUTH=(-H "Authorization: Bearer ${TOKEN}")
JSON=(-H "Content-Type: application/json")

say "Nashr API — Session W / P1 route transcript"
say "generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
say "server:    scripts/wire_stub_api.py (real routers, in-memory Supabase/R2/ledger/queue)"
say "bearer:    throwaway JWT minted by the stub; signs nothing outside this process"

# ---------------------------------------------------------------- 1.1 discovery
hit "1.1 GET /jobs?project_id — latest job for a READY project (SUCCESS)" \
  "${BASE}/jobs?project_id=${P_READY}" "${AUTH[@]}"

hit "1.1 GET /jobs?project_id — FAILED project: refunded fact + timestamps (SUCCESS)" \
  "${BASE}/jobs?project_id=${P_FAILED}" "${AUTH[@]}"

hit "1.1 GET /jobs?project_id — project with no job (FAILURE: 404 job_not_found)" \
  "${BASE}/jobs?project_id=${P_EMPTY}" "${AUTH[@]}"

hit "1.1 GET /jobs?project_id — someone else's project (FAILURE: 404 project_not_found)" \
  "${BASE}/jobs?project_id=${P_FOREIGN}" "${AUTH[@]}"

hit "1.1 GET /jobs/{id} — extended JobView on a completed run (SUCCESS)" \
  "${BASE}/jobs/${J_DONE}" "${AUTH[@]}"

hit "1.1 GET /jobs/{id} — failed run, refunded=true (SUCCESS)" \
  "${BASE}/jobs/${J_FAILED}" "${AUTH[@]}"

# ------------------------------------------------------------------- 1.4 topic
hit "1.4 POST /jobs — topic rides the enqueue payload (SUCCESS)" \
  -X POST "${BASE}/jobs" "${AUTH[@]}" "${JSON[@]}" -d "$(cat <<JSONBODY
{"project_id":"${P_EMPTY}","package":"presentation_standard",
 "sources":[{"storage_key":"${SRC_KEY}","filename":"aral-sea-2019.pdf"}],
 "language":"uz",
 "topic":"2019 va 2023 yil suv sarfini solishtir, siyosiy tavsiya bilan yakunla"}
JSONBODY
)"

hit "1.4 POST /jobs — unregistered source key (FAILURE: 422 unregistered_source)" \
  -X POST "${BASE}/jobs" "${AUTH[@]}" "${JSON[@]}" \
  -d "{\"project_id\":\"${P_EMPTY}\",\"sources\":[{\"storage_key\":\"sources/forged/x.pdf\",\"filename\":\"x.pdf\"}]}"

# --------------------------------------------------------------- 1.4 interview
hit "1.4 POST /projects/{id}/interview — source-derived questions (SUCCESS)" \
  -X POST "${BASE}/projects/${P_READY}/interview" "${AUTH[@]}" "${JSON[@]}" -d '{"language":"uz"}'

hit "1.4 POST /projects/{id}/interview — no processed sources (FAILURE: 409 sources_not_ready)" \
  -X POST "${BASE}/projects/${P_EMPTY}/interview" "${AUTH[@]}" "${JSON[@]}" -d '{"language":"uz"}'

# --------------------------------------------------------------------- 1.2 chat
hit "1.2 GET /projects/{id}/chat — empty thread, allowance intact (SUCCESS)" \
  "${BASE}/projects/${P_READY}/chat" "${AUTH[@]}"

hit "1.2 POST /projects/{id}/chat — a fix turn queues a presentation_edit job (SUCCESS)" \
  -X POST "${BASE}/projects/${P_READY}/chat" "${AUTH[@]}" "${JSON[@]}" \
  -d '{"message":"3-slayddagi sanani 2010 ga tuzat"}'

hit "1.2 POST /projects/{id}/chat — second turn while the edit job runs (FAILURE: 409 brain_busy)" \
  -X POST "${BASE}/projects/${P_READY}/chat" "${AUTH[@]}" "${JSON[@]}" \
  -d '{"message":"yana bitta tuzatish"}'

hit "1.2 GET /projects/{id}/chat — thread after the fix turn; applying_job_id set (SUCCESS)" \
  "${BASE}/projects/${P_READY}/chat" "${AUTH[@]}"

hit "1.2 GET /projects/{id}/chat — project with no brain session: can_edit=false (SUCCESS)" \
  "${BASE}/projects/${P_EMPTY}/chat" "${AUTH[@]}"

hit "1.2 POST /projects/{id}/chat/approve — nothing parked (FAILURE: 409 no_pending_action)" \
  -X POST "${BASE}/projects/${P_EMPTY}/chat/approve" "${AUTH[@]}"

hit "1.2 POST /projects/{id}/chat — someone else's project (FAILURE: 404 project_not_found)" \
  -X POST "${BASE}/projects/${P_FOREIGN}/chat" "${AUTH[@]}" "${JSON[@]}" -d '{"message":"salom"}'

# ------------------------------------------------------------------ 1.3 credits
hit "1.3 GET /credits — balance (SUCCESS)" "${BASE}/credits" "${AUTH[@]}"

hit "1.3 GET /credits — no bearer (FAILURE: 401 missing_bearer_token)" "${BASE}/credits"

hit "1.3 GET /credits/ledger?limit=5 — refunds and learning rewards visible (SUCCESS)" \
  "${BASE}/credits/ledger?limit=5" "${AUTH[@]}"

hit "1.3 GET /credits/ledger?limit=0 (FAILURE: 422 out of range)" \
  "${BASE}/credits/ledger?limit=0" "${AUTH[@]}"

hit "1.3 GET /pricing — the single source of truth, no auth (SUCCESS)" "${BASE}/pricing"

# ------------------------------------------------------------------ 1.5 refresh
hit "1.5 POST /auth/refresh — slides a live session forward (SUCCESS)" \
  -X POST "${BASE}/auth/refresh" "${AUTH[@]}"

hit "1.5 POST /auth/refresh — already-expired token (FAILURE: 401 expired)" \
  -X POST "${BASE}/auth/refresh" -H "Authorization: Bearer ${EXPIRED}"

# --------------------------------------------------------- 2.6/G19 public deck
hit "G19 GET /public/decks/{token} — recipients get downloads[] (SUCCESS)" \
  "${BASE}/public/decks/${SHARE}"

hit "G19 GET /public/decks/{token} — unknown token (FAILURE: 404 not_found)" \
  "${BASE}/public/decks/wire-stub-share-token-DEADBEEF"

say ""
say "=============================================================================="
say "end of transcript"

# Response bodies can carry a freshly minted token (POST /auth/refresh proves
# it mints one). Keep the shape, drop the material.
sed -i -E 's/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+/<JWT redacted>/g' "$OUT"

kill "$SERVER_PID" 2>/dev/null
echo "wrote ${OUT}"
