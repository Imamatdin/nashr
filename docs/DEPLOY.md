# Droplet deploy (standing procedure)

Quick reference for agents and operators. Full first-time setup lives in
[`DEPLOY.md`](../DEPLOY.md) at the repo root.

## SSH

Droplet host alias: **`ssh nashr`** (configured in Iko's `~/.ssh/config` on the
machine that deploys — `HostName 46.101.150.144`, key `nashr_key`, keepalives).

Agents deploy and run gates only when explicitly requested. Do **not** hand-edit
droplet state (`docker cp`, manual file edits on the server). The droplet must
stay reproducible from git.

**Standing rule for agents:** do not run gates or any other production actions
beyond the deploy steps explicitly requested in the task. Gate runs create real
Supabase projects, real LLM spend, and real escalation transcripts; they must
never run silently. If a gate is needed, flag it in the report and wait for
confirmation.

## Routine code deploy

Code is **COPY'd into the Docker image** — every code change needs pull + rebuild:

```bash
ssh nashr "cd /root/nashr && git fetch origin && git pull origin <branch> && docker compose up -d --build bot"
```

Verify the container:

```bash
ssh nashr "docker ps --filter name=nashr-bot --format '{{.Status}}'"
```

Confirm commits on the droplet:

```bash
ssh nashr "cd /root/nashr && git log --oneline -3"
```

## Migrations

The droplet has **no Postgres password**. Apply Supabase migrations via the
**Supabase SQL editor** (paste from `supabase/migrations/`), not from the VPS.

## Gates (live, inside the bot container)

Run from repo root on the droplet host, via `docker exec`:

```bash
ssh nashr "docker exec nashr-bot bash -lc 'cd /app && python scripts/gate_build2_stage0.py'"
ssh nashr "docker exec nashr-bot bash -lc 'cd /app && python scripts/gate_build2_stage1.py'"
ssh nashr "docker exec nashr-bot bash -lc 'cd /app && python scripts/gate_build2_stage3.py'"
ssh nashr "docker exec nashr-bot bash -lc 'cd /app && python scripts/gate_build2_stage4.py'"
ssh nashr "docker exec nashr-bot bash -lc 'cd /app && python scripts/gate_build2_stage5a.py'"
```

Use `python -m scripts.<gate>` only if the script is written as a module; the
gates above are invoked as `python scripts/<name>.py` per their file headers.

**Stage 5a gate:** requires Iko-filled brain prompt slots in
`packages/core/brain_prompts.py` — do not run until those placeholders are real
text.

## Branch

Build 2 work ships on **`build1-content-critic`** until merged to `main`.
