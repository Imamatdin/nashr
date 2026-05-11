"""Behavior tests for every pydantic model in ``packages.core.models``.

Each test exercises one specific contract: valid construction, invalid
rejection, validator behavior, or round-trip serialization. We avoid
``assert result is not None`` style smoke tests in favor of asserting the
actual semantic property under test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from packages.core.enums import (
    ArticleSectionStatus,
    ArticleStructure,
    Audience,
    CitationFormat,
    CitationStatus,
    ClaimStrength,
    ClaimType,
    CreditReason,
    CreditStatus,
    FileType,
    GenerationPackage,
    JobStatus,
    JobType,
    Language,
    OrderStatus,
    PaymentProvider,
    PrimaryUse,
    ProjectStatus,
    ProjectType,
    ResearchQuestionType,
    SourceQuality,
)
from packages.core.models import (
    AnswerScore,
    Article,
    ArticleCreate,
    ArticleOutline,
    ArticleSection,
    CitationRef,
    CreditLedgerEntry,
    EvidenceMatrixEntry,
    FileValidationResult,
    GenerationJob,
    Order,
    OutlineSection,
    Paragraph,
    ParsedPage,
    ParsedSource,
    Project,
    ProjectCreate,
    ResearchAnswer,
    ResearchQuestion,
    Source,
    SourceChunk,
    SourceChunkCreate,
    SourceClaim,
    SourceClaimCreate,
    SourceCreate,
    SourceMetadata,
    SourceMetadataExtracted,
    SourcePipelineResult,
    User,
    UserCreate,
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# user
# ---------------------------------------------------------------------------


def test_user_create_strips_whitespace_and_defaults_language() -> None:
    payload = UserCreate(telegram_id=12345, username="  imama  ")
    assert payload.telegram_id == 12345
    assert payload.username == "imama"
    assert payload.language is Language.UZ
    assert payload.primary_use is PrimaryUse.STUDY


def test_user_create_rejects_zero_telegram_id() -> None:
    with pytest.raises(ValidationError):
        UserCreate(telegram_id=0)


def test_user_round_trip_serialization() -> None:
    user = User(
        telegram_id=42,
        first_name="Iko",
        language=Language.EN,
        primary_use=PrimaryUse.RESEARCH,
        created_at=_now(),
    )
    dumped = user.model_dump()
    restored = User.model_validate(dumped)
    assert restored == user


# ---------------------------------------------------------------------------
# project
# ---------------------------------------------------------------------------


def test_project_create_valid() -> None:
    payload = ProjectCreate(
        user_id=uuid4(),
        type=ProjectType.PRESENTATION,
        title="Ag'artıwshılıq",
        language=Language.UZ,
        audience=Audience.TALABA,
    )
    assert payload.type is ProjectType.PRESENTATION


def test_project_rejects_blank_title() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(
            user_id=uuid4(),
            type=ProjectType.ARTICLE,
            title="",
            language=Language.RU,
            audience=Audience.AKADEMIK,
        )


def test_project_default_status_is_draft() -> None:
    now = _now()
    project = Project(
        user_id=uuid4(),
        type=ProjectType.ARTICLE,
        title="Climate research",
        language=Language.EN,
        audience=Audience.AKADEMIK,
        created_at=now,
        updated_at=now,
    )
    assert project.status is ProjectStatus.DRAFT


# ---------------------------------------------------------------------------
# source
# ---------------------------------------------------------------------------


def test_source_metadata_year_bounds() -> None:
    SourceMetadata(year=2024)
    with pytest.raises(ValidationError):
        SourceMetadata(year=1200)
    with pytest.raises(ValidationError):
        SourceMetadata(year=3000)


def test_source_create_rejects_oversized_files() -> None:
    payload_args: dict[str, object] = {
        "project_id": uuid4(),
        "filename": "huge.pdf",
        "file_type": FileType.PDF,
        "storage_key": "uploads/huge.pdf",
    }
    SourceCreate(**payload_args, file_size_bytes=20_971_520)
    with pytest.raises(ValidationError):
        SourceCreate(**payload_args, file_size_bytes=20_971_521)


def test_source_default_quality_is_medium() -> None:
    src = Source(
        project_id=uuid4(),
        filename="a.pdf",
        file_type=FileType.PDF,
        file_size_bytes=4096,
        storage_key="k",
        created_at=_now(),
    )
    assert src.quality is SourceQuality.MEDIUM
    assert src.metadata.authors == []


def test_source_chunk_text_capped_at_10000() -> None:
    SourceChunk(
        source_id=uuid4(),
        project_id=uuid4(),
        chunk_index=0,
        text="x" * 10_000,
        created_at=_now(),
    )
    with pytest.raises(ValidationError):
        SourceChunk(
            source_id=uuid4(),
            project_id=uuid4(),
            chunk_index=0,
            text="x" * 10_001,
            created_at=_now(),
        )


def test_paragraph_text_capped_at_5000() -> None:
    Paragraph(text="x" * 5_000)
    with pytest.raises(ValidationError):
        Paragraph(text="x" * 5_001)


def test_source_chunk_confidence_uses_tesseract_scale() -> None:
    SourceChunk(
        source_id=uuid4(),
        project_id=uuid4(),
        chunk_index=0,
        text="hello",
        confidence=87.5,
        created_at=_now(),
    )
    with pytest.raises(ValidationError):
        SourceChunk(
            source_id=uuid4(),
            project_id=uuid4(),
            chunk_index=0,
            text="hello",
            confidence=120.0,
            created_at=_now(),
        )


def test_source_claim_requires_strength_enum() -> None:
    SourceClaim(
        source_chunk_id=uuid4(),
        project_id=uuid4(),
        claim_text="x",
        quote="y",
        strength=ClaimStrength.STRONG,
        created_at=_now(),
    )
    with pytest.raises(ValidationError):
        SourceClaim(
            source_chunk_id=uuid4(),
            project_id=uuid4(),
            claim_text="x",
            quote="y",
            strength="super",  # type: ignore[arg-type]
            created_at=_now(),
        )


def test_source_chunk_create_round_trip() -> None:
    chunk = SourceChunkCreate(
        source_id="src-uuid",
        project_id="proj-uuid",
        chunk_index=7,
        text="Some chunk text.",
        page=2,
        is_ocr=True,
        confidence=87.5,
    )
    dumped = chunk.model_dump()
    restored = SourceChunkCreate.model_validate(dumped)
    assert restored == chunk


def test_source_claim_create_round_trip() -> None:
    claim = SourceClaimCreate(
        source_chunk_id="chunk-uuid",
        project_id="proj-uuid",
        claim_text="A factual claim long enough to validate.",
        quote="Supporting quote.",
        strength=ClaimStrength.MODERATE,
    )
    dumped = claim.model_dump()
    restored = SourceClaimCreate.model_validate(dumped)
    assert restored == claim


def test_source_claim_create_default_claim_type_is_general_fact() -> None:
    claim = SourceClaimCreate(
        claim_text="A factual claim long enough to validate.",
        quote=None,
        strength=ClaimStrength.MODERATE,
    )
    assert claim.claim_type is ClaimType.GENERAL_FACT


def test_source_claim_create_explicit_claim_type_round_trip() -> None:
    claim = SourceClaimCreate(
        source_chunk_id="chunk-uuid",
        project_id="proj-uuid",
        claim_text="Adoption rates increased by fifteen percent in the trial.",
        quote=None,
        strength=ClaimStrength.STRONG,
        claim_type=ClaimType.EMPIRICAL_FINDING,
    )
    dumped = claim.model_dump()
    restored = SourceClaimCreate.model_validate(dumped)
    assert restored == claim
    assert restored.claim_type is ClaimType.EMPIRICAL_FINDING


def test_source_claim_default_claim_type_is_general_fact() -> None:
    claim = SourceClaim(
        source_chunk_id=uuid4(),
        project_id=uuid4(),
        claim_text="A factual claim",
        quote=None,
        strength=ClaimStrength.STRONG,
        created_at=_now(),
    )
    assert claim.claim_type is ClaimType.GENERAL_FACT


def test_source_pipeline_result_round_trip() -> None:
    validation = FileValidationResult(
        valid=True,
        detected_type="pdf",
        mime_type="application/pdf",
        confidence=0.99,
        file_size_bytes=2048,
        extension_mismatch=False,
        rejection_reason=None,
        warning=None,
    )
    parsed = ParsedSource(
        filename="x.pdf",
        file_type="pdf",
        file_size_bytes=2048,
        pages=[ParsedPage(page_number=1, text="hello", char_count=5)],
        metadata=SourceMetadataExtracted(),
        full_text="hello",
        needs_ocr_pages=[],
        parse_errors=[],
    )
    chunk = SourceChunkCreate(chunk_index=0, text="hello", page=1)
    claim = SourceClaimCreate(
        claim_text="A factual claim of valid length here.",
        quote=None,
        strength=ClaimStrength.STRONG,
    )
    result = SourcePipelineResult(
        validation=validation,
        parsed=parsed,
        chunks=[chunk],
        claims=[claim],
        errors=["a warning"],
    )
    dumped = result.model_dump()
    restored = SourcePipelineResult.model_validate(dumped)
    assert restored == result


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------


def test_answer_score_axes_clamped_to_0_5() -> None:
    AnswerScore(specificity=0, source_grounding=5, usefulness=3)
    with pytest.raises(ValidationError):
        AnswerScore(specificity=-1, source_grounding=3, usefulness=3)
    with pytest.raises(ValidationError):
        AnswerScore(specificity=6, source_grounding=3, usefulness=3)


def test_evidence_matrix_entry_optional_links_default_none() -> None:
    entry = EvidenceMatrixEntry(
        project_id=uuid4(),
        claim_id=uuid4(),
        source_chunk_id=uuid4(),
        citation_status=CitationStatus.NEEDS_USER_INPUT,
        created_at=_now(),
    )
    assert entry.user_answer_id is None
    assert entry.article_section_id is None


def test_research_question_each_type_constructs() -> None:
    for qtype in ResearchQuestionType:
        q = ResearchQuestion(
            project_id=uuid4(),
            question_text="What is the thesis?",
            question_type=qtype,
            created_at=_now(),
        )
        assert q.question_type is qtype


def test_research_answer_credits_bounded() -> None:
    base: dict[str, object] = {
        "project_id": uuid4(),
        "question_id": uuid4(),
        "answer_text": "An answer.",
        "score": AnswerScore(specificity=4, source_grounding=4, usefulness=5),
        "created_at": _now(),
    }
    ResearchAnswer(**base, credits_earned=3)
    with pytest.raises(ValidationError):
        ResearchAnswer(**base, credits_earned=-1)
    with pytest.raises(ValidationError):
        ResearchAnswer(**base, credits_earned=11)


# ---------------------------------------------------------------------------
# article
# ---------------------------------------------------------------------------


def _outline() -> ArticleOutline:
    return ArticleOutline(
        title="Ag'artıwshılıq haqqında",
        structure=ArticleStructure.REFERAT,
        sections=[
            OutlineSection(
                title="Kirish",
                target_words=300,
                key_claims_to_use=["claim_1"],
                purpose="Frame the topic",
            ),
            OutlineSection(
                title="Asosiy qism",
                target_words=900,
                key_claims_to_use=[],
                purpose="Develop the argument",
            ),
        ],
        thesis="The Enlightenment reshaped European thought.",
        total_target_words=1500,
    )


def test_article_outline_requires_at_least_one_section() -> None:
    with pytest.raises(ValidationError):
        ArticleOutline(
            title="t",
            structure=ArticleStructure.REFERAT,
            sections=[],
            thesis="t",
            total_target_words=100,
        )


def test_article_create_round_trip() -> None:
    payload = ArticleCreate(
        project_id=uuid4(),
        structure_type=ArticleStructure.KURS_ISHI,
        thesis="The thesis.",
        citation_format=CitationFormat.GOST,
        target_pages=12,
    )
    again = ArticleCreate.model_validate(payload.model_dump())
    assert again == payload


def test_article_section_default_status_is_draft() -> None:
    section = ArticleSection(
        article_id=uuid4(),
        section_index=0,
        title="Kirish",
        paragraphs=[
            Paragraph(
                text="Hello world.",
                citations=[CitationRef(source_id=uuid4(), claim_id=uuid4())],
            )
        ],
        word_count=2,
        created_at=_now(),
    )
    assert section.status is ArticleSectionStatus.DRAFT


def test_article_constructs_with_outline() -> None:
    article = Article(
        project_id=uuid4(),
        structure_type=ArticleStructure.ILMIY_MAQOLA,
        thesis="A novel finding.",
        outline=_outline(),
        citation_format=CitationFormat.APA,
        target_pages=10,
        created_at=_now(),
        updated_at=_now(),
    )
    assert article.outline.total_target_words == 1500


# ---------------------------------------------------------------------------
# billing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(CreditReason))
def test_credit_ledger_entry_each_reason(reason: CreditReason) -> None:
    entry = CreditLedgerEntry(
        user_id=uuid4(),
        amount=5,
        reason=reason,
        created_at=_now(),
    )
    assert entry.reason is reason
    assert entry.status is CreditStatus.CONFIRMED


def test_credit_ledger_entry_can_be_negative_for_spend() -> None:
    entry = CreditLedgerEntry(
        user_id=uuid4(),
        amount=-1,
        reason=CreditReason.PRESENTATION_GENERATION,
        created_at=_now(),
    )
    assert entry.amount == -1


def test_order_amount_must_be_positive() -> None:
    base: dict[str, object] = {
        "user_id": uuid4(),
        "package_type": GenerationPackage.PRESENTATION_PREMIUM,
        "payment_provider": PaymentProvider.PAYME,
        "created_at": _now(),
    }
    Order(**base, amount_uzs=15_000)
    with pytest.raises(ValidationError):
        Order(**base, amount_uzs=0)
    with pytest.raises(ValidationError):
        Order(**base, amount_uzs=-1)


def test_order_default_status_pending() -> None:
    order = Order(
        user_id=uuid4(),
        amount_uzs=10_000,
        package_type=GenerationPackage.PRESENTATION_STANDARD,
        payment_provider=PaymentProvider.CLICK,
        created_at=_now(),
    )
    assert order.status is OrderStatus.PENDING
    assert order.paid_at is None


def test_order_rejects_unknown_package_type() -> None:
    with pytest.raises(ValidationError):
        Order(
            user_id=uuid4(),
            amount_uzs=10_000,
            package_type="enterprise_unlimited",  # type: ignore[arg-type]
            payment_provider=PaymentProvider.PAYME,
            created_at=_now(),
        )


def test_generation_job_defaults_zero_counters() -> None:
    job = GenerationJob(
        project_id=uuid4(),
        job_type=JobType.PRESENTATION_GENERATION,
        estimated_cost_uzs=1000,
        created_at=_now(),
    )
    assert job.status is JobStatus.QUEUED
    assert job.actual_cost_uzs == 0
    assert job.input_tokens_total == 0
    assert job.output_tokens_total == 0


def test_generation_job_rejects_negative_counters() -> None:
    with pytest.raises(ValidationError):
        GenerationJob(
            project_id=uuid4(),
            job_type=JobType.EXPORT,
            estimated_cost_uzs=-1,
            created_at=_now(),
        )


# ---------------------------------------------------------------------------
# extra contract checks
# ---------------------------------------------------------------------------


def test_models_reject_unknown_extra_fields() -> None:
    with pytest.raises(ValidationError):
        UserCreate(telegram_id=1, role="admin")  # type: ignore[call-arg]


def test_uuid_default_factory_produces_uuid() -> None:
    src = Source(
        project_id=uuid4(),
        filename="a.pdf",
        file_type=FileType.PDF,
        file_size_bytes=1,
        storage_key="k",
        created_at=_now(),
    )
    assert isinstance(src.id, UUID)
