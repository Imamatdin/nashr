"""Stand-in render worker for the browser journey's delivery steps (B1-FIX2).

The journey must watch a paid deck go committed -> rendering -> delivered, and an
AI edit whose render fails, without model calls and without the real renderer.
This script drives the database exactly as the queue worker would, through the
same 016 functions, and prints JSON for the journey:

    python scripts/local_stack/delivery_fixture.py paid <user_id>
    python scripts/local_stack/delivery_fixture.py publish <render_job_id> <claim_token>
    python scripts/local_stack/delivery_fixture.py edit <project_id> <user_id>
    python scripts/local_stack/delivery_fixture.py fail <render_job_id> <claim_token>
    python scripts/local_stack/delivery_fixture.py empty <user_id>
    python scripts/local_stack/delivery_fixture.py delivered <project_id> <user_id>

``delivered`` (B1-FIX3, Codex A4) runs a paid generation's whole life - job,
commit, render claim, every export, completion - in ONE transaction, so a page
polling the project can never observe it in flight: the first job it sees is
already completed.

A job's finish and the claim of the render it queued run in ONE transaction, so
the stack's own worker loop never sees that render queued. Works against every
migration 016 the journey runs on (the fixed one, fdb14bc's and 8cc000b's for
the pre-fix runs): it reads the schema from the catalogue. Talks only to the local
Postgres container and the local S3 stand-in; refuses anything else.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parent)]

import boto3  # noqa: E402
from local_env import S3_URL  # noqa: E402

import tests.unit.test_database_client as deck_fixtures  # noqa: E402
from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult  # noqa: E402
from packages.bot.sessions.serialization import serialize_sources  # noqa: E402
from packages.core.enums import AudienceType  # noqa: E402
from packages.platform.exports import renderer_version  # noqa: E402

CONTAINER = "nashr-local-pg"
BUCKET = "nashr-local"
# The renderer the API presents as current (a hash of the renderer source).
RENDERER = renderer_version()
WORKER = "journey-worker"
RENDER_WORKER = "journey-render"
PRICE = 10_000


def _sql(statement: str) -> str:
    """Run SQL in the local container; return the unaligned, tuples-only output."""

    done = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "psql",
            "-q",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "postgres",
        ],
        input=statement.encode(),
        check=True,
        capture_output=True,
    )
    return done.stdout.decode().strip()


def _literal(value: Any) -> str:
    return "$j$" + json.dumps(value) + "$j$"


def _fixed_schema() -> bool:
    """True on the fixed 016 (finish takes render_max_attempts), False on 8cc000b's."""

    arity = _sql("select max(pronargs) from pg_proc where proname = 'finish_generation_job'")
    return int(arity) == 11


def _has(sql_exists: str) -> bool:
    return _sql(f"select exists ({sql_exists})") == "t"


def _holds_in_table() -> bool:
    """B1-FIX3's 016: finish_generation_job records an edit's hold itself."""

    return _has("select 1 from pg_tables where tablename = 'edit_deliveries'")


def _holds_in_session() -> bool:
    """fdb14bc's 016: the worker's session write recorded the hold as JSON."""

    return _has(
        "select 1 from information_schema.columns where table_name = 'brain_sessions'"
        " and column_name = 'pending_deliveries_json'"
    )


def _finish_and_claim(
    job: str, base: str | None, content: dict[str, Any], kind: str, key: str
) -> dict[str, Any]:
    """finish_generation_job, then claim the render it queued, in one transaction."""

    attempts = ", 1" if _fixed_schema() else ""
    base_sql = f"'{base}'::uuid" if base else "null"
    out = _sql(
        f"""
        begin;
        select row_to_json(f) from finish_generation_job(
            '{job}', '{WORKER}', 1, {base_sql}, {_literal(content)}::jsonb, '{kind}', 1, '{key}',
            '{RENDERER}', '{{html,pdf,pptx}}'{attempts}) f;
        select row_to_json(c) from (
            select id, attempts from claim_job(
                (select id from generation_jobs where job_type = 'presentation_render'
                  and payload ->> 'requested_by_job' = '{job}'),
                '{RENDER_WORKER}')
        ) c;
        commit;
        """
    )
    finished, claimed = (json.loads(line) for line in out.splitlines() if line.startswith("{"))
    return {
        "job": job,
        "document": finished["document_id"],
        "revision": finished["revision_id"],
        "render": claimed["id"],
        "token": claimed["attempts"],
    }


def paid(user: str) -> dict[str, Any]:
    """A presentation project whose paid generation is committed and rendering."""

    project, job = str(uuid.uuid4()), str(uuid.uuid4())
    _sql(
        f"""
        insert into projects (id, user_id, type, title, language, audience, package_tier)
        values ('{project}', '{user}', 'presentation', 'Orol dengizi taqdimoti', 'uz', 'talaba',
                'presentation_standard');
        insert into generation_jobs (id, project_id, user_id, job_type, status, worker_id, payload,
                                     attempts, max_attempts, claimed_at, heartbeat_at, started_at)
        values ('{job}', '{project}', '{user}', 'presentation_generation', 'processing',
                '{WORKER}', {_literal({"package": "presentation_standard", "deducted_amount": PRICE})},
                1, 1, now(), now(), now());
        """
    )
    deck = deck_fixtures._make_deck(  # pyright: ignore[reportPrivateUsage]
        title="Orol dengizi", audience=AudienceType.UNDERGRADUATE
    )
    content = deck.model_dump(mode="json")
    content["project_id"] = project
    result = _finish_and_claim(job, None, content, "generation", f"job:{job}:deck")
    return {"project": project, **result}


def publish(render: str, token: int) -> dict[str, Any]:
    """Upload and register every requested format, then complete the render."""

    payload = json.loads(_sql(f"select payload from generation_jobs where id = '{render}'"))
    revision = payload["revision_id"]
    document = payload["document_id"]
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_URL,
        aws_access_key_id="local-access",
        aws_secret_access_key="local-secret",
        region_name="us-east-1",
    )
    for fmt in payload["formats"]:
        body = f"journey {fmt} export of {revision}".encode()
        sha = hashlib.sha256(body).hexdigest()
        key = f"exports/{document}/{revision}/{payload['renderer_version']}/{fmt}/{sha}.{fmt}"
        s3.put_object(Bucket=BUCKET, Key=key, Body=body)
        _sql(
            f"select status from register_export('{render}', '{RENDER_WORKER}', {token},"
            f" '{revision}', '{fmt}', '{payload['renderer_version']}', '{key}', '{sha}',"
            f" {len(body)}, null)"
        )
    done = _sql(f"select complete_job('{render}', '{RENDER_WORKER}', {token}, '{{}}'::jsonb)")
    return {"completed": done == "t"}


def edit(project: str, user: str) -> dict[str, Any]:
    """Open a chat session on the head, then commit an AI edit whose render is claimed."""

    head = json.loads(
        _sql(
            "select row_to_json(h) from (select d.id as document, r.id as revision, r.content"
            " from documents d join document_revisions r on r.id = d.head_revision_id"
            f" where d.project_id = '{project}' and d.kind = 'presentation') h"
        )
    )
    light, _figures = serialize_sources(SourceProcessingResult())
    _sql(
        f"""
        insert into brain_sessions (project_id, history_json, sources_json, figures_json, package,
                                    formats_json, approval_state, fixes_used,
                                    accumulated_cost_usd, accumulated_image_count, revision_id)
        values ('{project}', '[]', {_literal(light)}::jsonb, '[]', 'presentation_standard',
                '["html","pdf","pptx_editable"]', 'idle', 0, 0, 0, '{head["revision"]}')
        on conflict (project_id) do update set revision_id = excluded.revision_id;
        """
    )
    job = str(uuid.uuid4())
    _sql(
        f"""
        insert into generation_jobs (id, project_id, user_id, job_type, status, worker_id, payload,
                                     attempts, max_attempts, claimed_at, heartbeat_at, started_at)
        values ('{job}', '{project}', '{user}', 'presentation_edit', 'processing', '{WORKER}',
                {_literal({"document_id": head["document"], "base_revision_id": head["revision"], "slides_changed": 1})},
                1, 1, now(), now(), now());
        """
    )
    content = dict(head["content"])
    content["title"] = f"{content.get('title', 'Deck')} (tahrir)"
    result = _finish_and_claim(job, head["revision"], content, "ai_edit", f"chat-edit:{job}")
    # What the worker's dispatcher records for the edit. B1-FIX3: nothing about
    # the hold - finish_generation_job wrote it; the session only moves (a CAS
    # write). fdb14bc: the hold was session JSON. 8cc000b: the edit was counted
    # as delivered at once (its deliver() was a no-op).
    if _holds_in_table():
        _sql(
            f"update brain_sessions set revision_id = '{result['revision']}',"
            f" version = version + 1 where project_id = '{project}'"
        )
    elif _holds_in_session():
        pending = [{"job_id": job, "revision_id": result["revision"], "slides_changed": 1}]
        _sql(
            f"update brain_sessions set revision_id = '{result['revision']}',"
            f" pending_deliveries_json = {_literal(pending)}::jsonb where project_id = '{project}'"
        )
    else:
        _sql(
            f"update brain_sessions set revision_id = '{result['revision']}',"
            f" fixes_used = fixes_used + 1 where project_id = '{project}'"
        )
    return result


def fail(render: str, token: int) -> dict[str, Any]:
    """The render gives up for good (the journey's renders get one attempt)."""

    _sql(f"select fail_job('{render}', '{RENDER_WORKER}', {token}, 'render', 'chromium crashed')")
    status = _sql(f"select status from generation_jobs where id = '{render}'")
    return {"render_status": status}


def empty(user: str) -> dict[str, Any]:
    """A presentation project with no job and no deck yet."""

    project = str(uuid.uuid4())
    _sql(
        f"""
        insert into projects (id, user_id, type, title, language, audience, package_tier)
        values ('{project}', '{user}', 'presentation', 'Orol dengizi taqdimoti', 'uz', 'talaba',
                'presentation_standard');
        """
    )
    return {"project": project}


def delivered(project: str, user: str) -> dict[str, Any]:
    """A paid generation created, committed, rendered and completed in one transaction."""

    job = str(uuid.uuid4())
    deck = deck_fixtures._make_deck(  # pyright: ignore[reportPrivateUsage]
        title="Orol dengizi", audience=AudienceType.UNDERGRADUATE
    )
    content = deck.model_dump(mode="json")
    content["project_id"] = project
    attempts = ", 1" if _fixed_schema() else ""
    body = "'journey ' || f || ' export of ' || r.revision_id"
    digest = f"encode(sha256(convert_to({body}, 'UTF8')), 'hex')"
    out = _sql(
        f"""
        begin;
        insert into generation_jobs (id, project_id, user_id, job_type, status, worker_id, payload,
                                     attempts, max_attempts, claimed_at, heartbeat_at, started_at)
        values ('{job}', '{project}', '{user}', 'presentation_generation', 'processing',
                '{WORKER}', {_literal({"package": "presentation_standard", "deducted_amount": PRICE})},
                1, 1, now(), now(), now());
        create temp table finished on commit drop as
        select * from finish_generation_job(
            '{job}', '{WORKER}', 1, null, {_literal(content)}::jsonb, 'generation', 1,
            'job:{job}:deck', '{RENDERER}', '{{html,pdf,pptx}}'{attempts});
        create temp table render on commit drop as
        select c.id, c.attempts, f.revision_id, f.document_id
          from finished f,
               claim_job((select id from generation_jobs where job_type = 'presentation_render'
                           and payload ->> 'requested_by_job' = '{job}'), '{RENDER_WORKER}') c;
        select count(*) from render r, unnest(array['html', 'pdf', 'pptx']) f,
             register_export(
                 r.id, '{RENDER_WORKER}', r.attempts, r.revision_id, f, '{RENDERER}',
                 'exports/' || r.document_id || '/' || r.revision_id || '/{RENDERER}/' || f || '/'
                     || {digest} || '.' || f,
                 {digest}, octet_length(convert_to({body}, 'UTF8')), null);
        select complete_job(r.id, '{RENDER_WORKER}', r.attempts, '{{}}'::jsonb) from render r;
        select row_to_json(x) from (
            select r.revision_id, r.document_id, j.status
              from render r, generation_jobs j where j.id = '{job}') x;
        commit;
        """
    )
    state = json.loads(next(line for line in out.splitlines() if line.startswith("{")))
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_URL,
        aws_access_key_id="local-access",
        aws_secret_access_key="local-secret",
        region_name="us-east-1",
    )
    revision, document = state["revision_id"], state["document_id"]
    for fmt in ("html", "pdf", "pptx"):
        data = f"journey {fmt} export of {revision}".encode()
        sha = hashlib.sha256(data).hexdigest()
        key = f"exports/{document}/{revision}/{RENDERER}/{fmt}/{sha}.{fmt}"
        s3.put_object(Bucket=BUCKET, Key=key, Body=data)
    return {"project": project, "job": job, "status": state["status"]}


def main() -> None:
    command, *args = sys.argv[1:]
    if command == "paid":
        out = paid(args[0])
    elif command == "publish":
        out = publish(args[0], int(args[1]))
    elif command == "edit":
        out = edit(args[0], args[1])
    elif command == "fail":
        out = fail(args[0], int(args[1]))
    elif command == "empty":
        out = empty(args[0])
    elif command == "delivered":
        out = delivered(args[0], args[1])
    else:
        raise SystemExit(f"unknown command {command}")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
