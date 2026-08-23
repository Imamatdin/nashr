"""A stub-backed Nashr API for evidence walks (Session W).

Runs the REAL FastAPI app — real routers, real auth, real request/response
models — over in-memory fakes for Supabase, R2, the credit ledger, the job
queue and the brain driver. That makes a curl transcript against it evidence
about the ROUTES (shapes, status codes, gate order), which is exactly what the
P1 gate asks for, without a database, a worker, or a single spent credit.

    python scripts/wire_stub_api.py --port 8099

Prints a JSON banner with the bearer token and the seeded ids, then serves
until interrupted. Development tooling only — nothing here is importable by,
or reachable from, the production app.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
from packages.bot.sessions.driver import ScriptedStubDriver, StubResponse
from packages.bot.sessions.models import TurnAction
from packages.bot.sessions.serialization import serialize_sources
from packages.core.enums import (
    AudienceType,
    BackgroundTreatment,
    ClaimStrength,
    NarrativePhase,
    PresentationMood,
    SlideType,
)
from packages.core.models.presentation import (
    ColorPalette,
    DeckPlan,
    DeckSpec,
    DesignDirectionSpec,
    PlannedSection,
    PresentationInterviewAnswers,
    SlideContent,
    SlideFix,
    SlideSpec,
)
from packages.core.models.source import SourceChunkCreate, SourceClaimCreate
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditAction, CreditEntry, CreditLedger
from packages.platform.jobs import GenerationJob, JobStatus, JobType
from packages.platform.rate_limit import RateDecision

_SECRET = "wire-stub-jwt-secret"
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_USER_ID = UUID("22222222-2222-2222-2222-222222222222")
PROJECT_READY = "aaaaaaaa-0000-0000-0000-00000000000a"
PROJECT_FAILED = "aaaaaaaa-0000-0000-0000-00000000000b"
PROJECT_EMPTY = "aaaaaaaa-0000-0000-0000-00000000000c"
PROJECT_FOREIGN = "aaaaaaaa-0000-0000-0000-00000000000d"
JOB_COMPLETED = "bbbbbbbb-0000-0000-0000-00000000000a"
JOB_FAILED = "bbbbbbbb-0000-0000-0000-00000000000b"
SHARE_TOKEN = "wire-stub-share-token-abcdefgh"


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://stub.supabase.co",
        supabase_service_key="stub-service-key",
        telegram_bot_token="123456:stub",
        supabase_jwt_secret=_SECRET,
    )


def _deck(project_id: str) -> DeckSpec:
    palette = ColorPalette(
        background="#1A120B",
        surface="#D4C5A9",
        text="#F5F0E8",
        accent="#C4923A",
        text_secondary="#A89F91",
    )
    return DeckSpec(
        project_id=project_id,
        title="Orol dengizi qurishi",
        design=DesignDirectionSpec(
            mood=PresentationMood.WARM_HISTORICAL,
            palette=palette,
            heading_font="Playfair Display",
            body_font="EB Garamond",
            image_style_prefix="documentary photography, no text in image, ",
            background_treatment=BackgroundTreatment.DARK,
        ),
        interview=PresentationInterviewAnswers(audience=AudienceType.UNDERGRADUATE),
        plan=DeckPlan(
            thesis="Suv olib qo'yish Orol dengizini o'lchab bo'ladigan darajada qisqartirdi.",
            audience_takeaway="Tinglovchi qisqarishning sababini va ko'lamini ayta oladi.",
            sections=[
                PlannedSection(
                    section_name="Sabab",
                    thesis="Sug'orish kanallari oqimni burdi.",
                    phase=NarrativePhase.HOOK,
                ),
                PlannedSection(
                    section_name="Oqibat",
                    thesis="Suv sathi o'nlab metrga tushdi.",
                    phase=NarrativePhase.CLOSE,
                ),
            ],
            image_cohesion_note="Bitta izchil hujjatli vizual uslub.",
        ),
        slides=[
            SlideSpec(
                slide_index=0,
                slide_type=SlideType.TITLE_HERO,
                content=SlideContent(title="Orol dengizi qurishi"),
            ),
            SlideSpec(
                slide_index=1,
                slide_type=SlideType.SECTION_BREAK,
                content=SlideContent(title="Sabab"),
            ),
            SlideSpec(
                slide_index=2,
                slide_type=SlideType.SECTION_BREAK,
                content=SlideContent(title="Oqibat"),
            ),
        ],
    )


def _sources(source_id: str) -> SourceProcessingResult:
    return SourceProcessingResult(
        claims=[
            SourceClaimCreate(
                source_chunk_id=f"{source_id}:0",
                claim_text="1960-2010 yillarda Orol dengizi maydoni 90% ga qisqardi.",
                quote="the surface area fell by roughly ninety percent",
                strength=ClaimStrength.STRONG,
            ),
            SourceClaimCreate(
                source_chunk_id=f"{source_id}:1",
                claim_text="Amudaryo oqimining katta qismi sug'orishga burildi.",
                quote="most of the Amu Darya flow was diverted for irrigation",
                strength=ClaimStrength.MODERATE,
            ),
        ],
        chunks=[
            SourceChunkCreate(
                source_id=source_id,
                chunk_index=0,
                text="The Aral Sea surface area fell by roughly ninety percent between "
                "1960 and 2010, following large-scale irrigation diversion.",
                page=1,
            ),
            SourceChunkCreate(
                source_id=source_id,
                chunk_index=1,
                text="Most of the Amu Darya flow was diverted for irrigation of cotton "
                "across the basin, cutting inflow to the sea.",
                page=2,
            ),
        ],
    )


class StubDb:
    """In-memory stand-in for the Supabase-backed DatabaseClient."""

    def __init__(self) -> None:
        self.source_id = "cccccccc-0000-0000-0000-00000000000a"
        now = datetime.now(UTC).isoformat()
        self.projects: dict[str, dict[str, Any]] = {
            PROJECT_READY: {
                "id": PROJECT_READY,
                "user_id": str(USER_ID),
                "title": "Orol dengizi qurishi",
                "type": "presentation",
                "status": "ready",
                "share_token": SHARE_TOKEN,
                "package_tier": "presentation_premium",
                "created_at": now,
            },
            PROJECT_FAILED: {
                "id": PROJECT_FAILED,
                "user_id": str(USER_ID),
                "title": "Muvaffaqiyatsiz loyiha",
                "type": "presentation",
                "status": "failed",
                "share_token": None,
                "created_at": now,
            },
            PROJECT_EMPTY: {
                "id": PROJECT_EMPTY,
                "user_id": str(USER_ID),
                "title": "Yangi loyiha",
                "type": "presentation",
                "status": "draft",
                "share_token": None,
                "created_at": now,
            },
            PROJECT_FOREIGN: {
                "id": PROJECT_FOREIGN,
                "user_id": str(OTHER_USER_ID),
                "title": "Boshqa foydalanuvchi loyihasi",
                "type": "presentation",
                "status": "ready",
                "share_token": None,
                "created_at": now,
            },
        }
        light, figures = serialize_sources(_sources(self.source_id))
        self.brain_sessions: dict[str, dict[str, Any]] = {
            PROJECT_READY: {
                "project_id": PROJECT_READY,
                "history_json": [],
                "sources_json": light,
                "package": "presentation_premium",
                "formats_json": ["html", "pptx_editable", "pdf"],
                "approval_state": "idle",
                "pending_action_json": None,
                "fixes_used": 0,
                "accumulated_cost_usd": 0.0,
                "accumulated_image_count": 0,
            }
        }
        self.session_figures: dict[str, list[dict[str, Any]]] = {PROJECT_READY: figures}
        self.decks: dict[str, dict[str, Any]] = {
            PROJECT_READY: {"deck_json": _deck(PROJECT_READY).model_dump(mode="json")}
        }
        self.files: dict[str, list[dict[str, Any]]] = {
            PROJECT_READY: [
                {"file_type": "html", "storage_path": f"generated/{PROJECT_READY}/deck.html"},
                {"file_type": "pptx", "storage_path": f"generated/{PROJECT_READY}/deck.pptx"},
                {"file_type": "pdf", "storage_path": f"generated/{PROJECT_READY}/deck.pdf"},
            ]
        }
        self.sources: dict[str, list[dict[str, Any]]] = {
            PROJECT_READY: [
                {
                    "id": self.source_id,
                    "project_id": PROJECT_READY,
                    "filename": "aral-sea-2019.pdf",
                    "storage_key": f"sources/{PROJECT_READY}/aral-sea-2019.pdf",
                }
            ],
            PROJECT_EMPTY: [
                {
                    "id": self.source_id,
                    "project_id": PROJECT_EMPTY,
                    "filename": "aral-sea-2019.pdf",
                    "storage_key": f"sources/{PROJECT_EMPTY}/aral-sea-2019.pdf",
                }
            ],
        }

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self.projects.get(project_id)

    async def create_project(self, **kwargs: Any) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "user_id": kwargs["user_id"],
            "title": kwargs["title"],
            "type": kwargs["project_type"],
            "status": "draft",
            "share_token": None,
        }
        self.projects[str(row["id"])] = row
        return row

    async def get_project_sources(self, project_id: str) -> list[dict[str, Any]]:
        return self.sources.get(project_id, [])

    async def get_project_files(self, project_id: str) -> list[dict[str, Any]]:
        return self.files.get(project_id, [])

    async def set_project_share_token(self, project_id: str, token: str | None) -> None:
        self.projects[project_id]["share_token"] = token

    async def set_project_package_tier(self, project_id: str, tier: str) -> None:
        self.projects[project_id]["package_tier"] = tier

    async def get_project_by_share_token(self, token: str) -> dict[str, Any] | None:
        for row in self.projects.values():
            if row.get("share_token") == token:
                return row
        return None

    async def get_brain_session(self, project_id: str) -> dict[str, Any] | None:
        return self.brain_sessions.get(project_id)

    async def get_brain_session_sources(self, project_id: str) -> dict[str, Any] | None:
        row = self.brain_sessions.get(project_id)
        return cast("dict[str, Any] | None", row["sources_json"]) if row else None

    async def get_brain_session_figures(self, project_id: str) -> list[dict[str, Any]] | None:
        return self.session_figures.get(project_id)

    async def save_brain_session(self, project_id: str, **kwargs: Any) -> None:
        row = self.brain_sessions.setdefault(project_id, {"project_id": project_id})
        for key, value in kwargs.items():
            if key == "figures_json" and value is None:
                continue
            row[key] = value

    async def get_deck(self, project_id: str) -> dict[str, Any] | None:
        return self.decks.get(project_id)

    async def save_deck(self, project_id: str, deck_spec: DeckSpec) -> dict[str, Any]:
        row = {"deck_json": deck_spec.model_dump(mode="json")}
        self.decks[project_id] = row
        return row


class StubCredits:
    """Ledger stand-in: a real append-only list, real balance arithmetic."""

    PRICING = CreditLedger.PRICING
    FREE_CREDIT_VALUE = CreditLedger.FREE_CREDIT_VALUE
    FREE_DAILY_CAP = CreditLedger.FREE_DAILY_CAP
    FREE_WEEKLY_CAP = CreditLedger.FREE_WEEKLY_CAP
    FREE_PROJECT_CAP = CreditLedger.FREE_PROJECT_CAP

    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.entries: list[CreditEntry] = [
            CreditEntry(
                id="ledger-1",
                user_id=str(USER_ID),
                project_id=None,
                action=CreditAction.GRANT_PAID,
                amount=50_000,
                reason="payment",
                created_at=now - timedelta(days=3),
            ),
            CreditEntry(
                id="ledger-2",
                user_id=str(USER_ID),
                project_id=PROJECT_READY,
                action=CreditAction.GRANT_FREE,
                amount=5_000,
                reason="learning_reward",
                created_at=now - timedelta(days=2),
            ),
            CreditEntry(
                id="ledger-3",
                user_id=str(USER_ID),
                project_id=PROJECT_READY,
                action=CreditAction.DEDUCT_PRESENTATION,
                amount=-15_000,
                reason="generation:presentation_premium",
                created_at=now - timedelta(days=2),
            ),
            CreditEntry(
                id="ledger-4",
                user_id=str(USER_ID),
                project_id=PROJECT_FAILED,
                action=CreditAction.DEDUCT_PRESENTATION,
                amount=-10_000,
                reason="generation:presentation_standard",
                created_at=now - timedelta(days=1),
            ),
            CreditEntry(
                id="ledger-5",
                user_id=str(USER_ID),
                project_id=PROJECT_FAILED,
                generation_job_id=JOB_FAILED,
                action=CreditAction.REFUND,
                amount=10_000,
                reason="refund",
                created_at=now - timedelta(hours=23),
            ),
        ]
        self.deductions: list[tuple[str, str, str]] = []
        self.refund_calls: list[dict[str, Any]] = []

    async def get_balance(self, user_id: str) -> int:
        return sum(e.amount for e in self.entries if e.user_id == user_id)

    async def get_ledger(self, user_id: str, limit: int = 50) -> list[CreditEntry]:
        rows = [e for e in self.entries if e.user_id == user_id]
        rows.sort(key=lambda e: e.created_at, reverse=True)
        return rows[:limit]

    async def has_sufficient_credits(self, user_id: str, product_type: str) -> bool:
        return await self.get_balance(user_id) >= self.PRICING[product_type]

    async def has_refund_for_job(self, user_id: str, generation_job_id: str) -> bool:
        return any(
            e.user_id == user_id
            and e.generation_job_id == generation_job_id
            and e.action is CreditAction.REFUND
            for e in self.entries
        )

    async def deduct_for_generation(
        self, user_id: str, project_id: str, product_type: str
    ) -> CreditEntry:
        self.deductions.append((user_id, project_id, product_type))
        entry = CreditEntry(
            id=f"ledger-{len(self.entries) + 1}",
            user_id=user_id,
            project_id=project_id,
            action=CreditAction.DEDUCT_PRESENTATION,
            amount=-self.PRICING[product_type],
            reason=f"generation:{product_type}",
        )
        self.entries.append(entry)
        return entry

    async def refund(
        self,
        user_id: str,
        project_id: str,
        amount_uzs: int,
        reason: str,
        *,
        generation_job_id: str | None = None,
    ) -> CreditEntry:
        self.refund_calls.append(
            {"user_id": user_id, "amount": amount_uzs, "job": generation_job_id}
        )
        entry = CreditEntry(
            id=f"ledger-{len(self.entries) + 1}",
            user_id=user_id,
            project_id=project_id,
            generation_job_id=generation_job_id,
            action=CreditAction.REFUND,
            amount=amount_uzs,
            reason=reason,
        )
        self.entries.append(entry)
        return entry


class StubQueue:
    """Job queue stand-in over an in-memory row list."""

    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.jobs: dict[str, GenerationJob] = {
            JOB_COMPLETED: GenerationJob.model_validate(
                {
                    "id": JOB_COMPLETED,
                    "project_id": PROJECT_READY,
                    "user_id": str(USER_ID),
                    "job_type": "presentation_generation",
                    "status": "completed",
                    "payload": {
                        "package": "presentation_premium",
                        "product_type": "presentation_premium",
                        "deducted_amount": 15_000,
                        "topic": "2019 va 2023 yil suv sarfini solishtir",
                    },
                    "progress": {
                        "step": "Rendering presentation",
                        "current": 7,
                        "total": 7,
                    },
                    "created_at": (now - timedelta(minutes=20)).isoformat(),
                    "started_at": (now - timedelta(minutes=19)).isoformat(),
                    "heartbeat_at": (now - timedelta(minutes=15)).isoformat(),
                    "completed_at": (now - timedelta(minutes=15)).isoformat(),
                }
            ),
            JOB_FAILED: GenerationJob.model_validate(
                {
                    "id": JOB_FAILED,
                    "project_id": PROJECT_FAILED,
                    "user_id": str(USER_ID),
                    "job_type": "presentation_generation",
                    "status": "failed",
                    "payload": {
                        "package": "presentation_standard",
                        "product_type": "presentation_standard",
                        "deducted_amount": 10_000,
                    },
                    "progress": {
                        "step": "Choosing design direction",
                        "current": 4,
                        "total": 7,
                    },
                    "error_message": "editorial: RuntimeError: grounding hard stop",
                    "created_at": (now - timedelta(hours=24)).isoformat(),
                    "started_at": (now - timedelta(hours=24)).isoformat(),
                    "heartbeat_at": (now - timedelta(hours=23, minutes=57)).isoformat(),
                    "completed_at": (now - timedelta(hours=23, minutes=57)).isoformat(),
                }
            ),
        }
        self.enqueued: list[dict[str, Any]] = []

    def _rows(self, project_id: str, job_type: JobType) -> list[GenerationJob]:
        return [
            job
            for job in self.jobs.values()
            if job.project_id == project_id and job.job_type is job_type
        ]

    async def get_active_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        for job in self._rows(project_id, job_type):
            if job.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
                return job
        return None

    async def get_latest_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        rows = self._rows(project_id, job_type)
        if not rows:
            return None
        return sorted(rows, key=lambda j: j.created_at or datetime.min.replace(tzinfo=UTC))[-1]

    async def get_job(self, job_id: str) -> GenerationJob | None:
        return self.jobs.get(job_id)

    async def enqueue(self, **kwargs: Any) -> GenerationJob:
        self.enqueued.append(kwargs)
        job = GenerationJob.model_validate(
            {
                "id": str(uuid.uuid4()),
                "project_id": kwargs["project_id"],
                "user_id": kwargs["user_id"],
                "job_type": kwargs["job_type"].value,
                "status": "queued",
                "payload": kwargs["payload"],
                "progress": {},
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        self.jobs[job.id] = job
        return job


class StubLimiter:
    """Always-allow limiter with an env-free switch for the 429 transcript."""

    def __init__(self) -> None:
        self.allowed = True

    def _decision(self, action: str, scope: str) -> RateDecision:
        return RateDecision(
            allowed=self.allowed,
            scope=scope,
            action=action,
            count=11 if not self.allowed else 1,
            limit=10,
            resets_at=datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1),
        )

    async def check(self, *, action: str, user_id: str, ip: str) -> RateDecision:
        return self._decision(action, "user")

    async def check_ip(self, *, action: str, ip: str) -> RateDecision:
        return self._decision(action, "ip")


class StubIdentity:
    """Only the one method the auth routes call on the identity service."""

    def mint_session(self, user_id: UUID) -> Any:
        return mint_app_jwt(_SECRET, user_id, 3600)


class StubStorage:
    available = True

    async def signed_url(self, key: str, expires_in: int = 3600) -> str:
        return f"https://r2.stub.local/{key}?X-Amz-Expires={expires_in}&X-Amz-Signature=stub"


def build_app(*, limiter: StubLimiter | None = None) -> Any:
    """The real app over stub state, with a scripted brain driver."""

    resolved_limiter = limiter or StubLimiter()

    def driver_factory() -> ScriptedStubDriver:
        # One scripted fix turn, then plain replies. The route decides what to
        # do with it; the driver only produces the turn, exactly as the real
        # Gemini driver does.
        return ScriptedStubDriver(
            script=[
                StubResponse(
                    action=TurnAction.FIX,
                    reply_text="3-slayddagi sanani tuzatdim.",
                    fixes=(
                        SlideFix(
                            slide_id=_deck(PROJECT_READY).slides[2].slide_id,
                            instruction="Sanani 2010 ga o'zgartir.",
                        ),
                    ),
                    call_count=1,
                )
            ]
        )

    return create_app(
        config=_config(),
        db=cast(Any, StubDb()),
        identity_service=cast(Any, StubIdentity()),
        credits=cast(Any, StubCredits()),
        job_queue=cast(Any, StubQueue()),
        rate_limiter=cast(Any, resolved_limiter),
        storage=cast(Any, StubStorage()),
        brain_driver_factory=driver_factory,
    )


def banner() -> dict[str, str]:
    return {
        "bearer": mint_app_jwt(_SECRET, USER_ID, 3600).access_token,
        "expired_bearer": mint_app_jwt(_SECRET, USER_ID, -10).access_token,
        "user_id": str(USER_ID),
        "project_ready": PROJECT_READY,
        "project_failed": PROJECT_FAILED,
        "project_empty": PROJECT_EMPTY,
        "project_foreign": PROJECT_FOREIGN,
        "job_completed": JOB_COMPLETED,
        "job_failed": JOB_FAILED,
        "share_token": SHARE_TOKEN,
        "source_key": f"sources/{PROJECT_EMPTY}/aral-sea-2019.pdf",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stub-backed Nashr API for evidence walks")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument(
        "--banner-only",
        action="store_true",
        help="print the token/ids JSON and exit (the curl script reads this)",
    )
    args = parser.parse_args()

    print(json.dumps(banner()), flush=True)
    if args.banner_only:
        return 0

    import uvicorn

    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
