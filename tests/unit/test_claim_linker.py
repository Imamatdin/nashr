"""Behaviour tests for :class:`ClaimLinker`.

The linker is intentionally simple: it matches claim text against the
``key_claims_to_use`` strings on each outline section using a Jaccard
overlap of stop-word-stripped tokens. Tests pin:

* exact and partial matches at and below the configured threshold;
* tie-breaking when a claim plausibly fits more than one section;
* assignment uniqueness — every matched claim ends up in exactly one
  section, never duplicated;
* multi-script behaviour for Latin Uzbek and Cyrillic Russian text.
"""

from __future__ import annotations

from uuid import uuid4

from packages.core.enums import ArticleStructure, ClaimStrength
from packages.core.models import (
    ArticleOutline,
    OutlineSection,
    SourceClaimCreate,
)
from packages.workers.article import ClaimLinker


def _claim(text: str) -> SourceClaimCreate:
    return SourceClaimCreate(
        source_chunk_id="0",
        claim_text=text,
        strength=ClaimStrength.MODERATE,
    )


def _outline_with_keys(sections: list[tuple[str, list[str]]]) -> ArticleOutline:
    return ArticleOutline(
        title="Test article",
        structure=ArticleStructure.REFERAT,
        sections=[
            OutlineSection(
                title=title,
                target_words=300,
                key_claims_to_use=keys,
                purpose=f"Purpose for {title}",
            )
            for title, keys in sections
        ],
        thesis="A thesis statement long enough to satisfy the model.",
        total_target_words=300 * len(sections),
    )


def test_link_exact_match() -> None:
    linker = ClaimLinker()
    claims = [
        _claim("Renewable energy adoption transforms electricity markets globally."),
    ]
    outline = _outline_with_keys(
        [
            ("Introduction", ["renewable energy adoption global markets"]),
            ("Conclusion", ["future research directions"]),
        ]
    )

    mapping = linker.link_claims_to_sections(claims, outline)

    intro_id = str(outline.sections[0].id)
    assert mapping[intro_id] == [0]
    conclusion_id = str(outline.sections[1].id)
    assert conclusion_id not in mapping or mapping[conclusion_id] == []


def test_link_partial_overlap_above_threshold() -> None:
    linker = ClaimLinker()
    claims = [
        _claim("Solar panel efficiency continues improving each manufacturing generation."),
    ]
    outline = _outline_with_keys(
        [("Body", ["solar panel manufacturing efficiency improvements"])],
    )

    mapping = linker.link_claims_to_sections(claims, outline)

    section_id = str(outline.sections[0].id)
    assert mapping[section_id] == [0]


def test_link_no_match_below_threshold() -> None:
    linker = ClaimLinker()
    claims = [
        _claim("Quantum entanglement enables superdense coding protocols entirely."),
    ]
    outline = _outline_with_keys(
        [("Body", ["medieval Uzbek poetry stylistic conventions"])],
    )

    mapping = linker.link_claims_to_sections(claims, outline)

    for indices in mapping.values():
        assert 0 not in indices


def test_link_claim_goes_to_best_section() -> None:
    linker = ClaimLinker()
    claims = [
        _claim("Economic policy reforms reshaped agricultural production output significantly."),
    ]
    outline = _outline_with_keys(
        [
            ("Section A", ["agriculture"]),
            ("Section B", ["economic policy reforms agricultural production output"]),
        ]
    )

    mapping = linker.link_claims_to_sections(claims, outline)

    section_a_id = str(outline.sections[0].id)
    section_b_id = str(outline.sections[1].id)
    assert mapping.get(section_b_id) == [0]
    assert 0 not in mapping.get(section_a_id, [])


def test_link_claim_assigned_to_only_one_section() -> None:
    linker = ClaimLinker()
    claims = [_claim("Renewable energy policy drives renewable adoption globally.")]
    outline = _outline_with_keys(
        [
            ("S1", ["renewable energy policy"]),
            ("S2", ["renewable energy adoption"]),
        ]
    )

    mapping = linker.link_claims_to_sections(claims, outline)

    appearances = sum(1 for indices in mapping.values() if 0 in indices)
    assert appearances == 1


def test_link_uzbek_text() -> None:
    linker = ClaimLinker()
    claims = [_claim("Ag'artıwshılıq dáwiri Yevropa filosofiyasin tubinen ózgertti.")]
    outline = _outline_with_keys(
        [("Kirish", ["Ag'artıwshılıq Yevropa filosofiya"])],
    )

    mapping = linker.link_claims_to_sections(claims, outline)

    section_id = str(outline.sections[0].id)
    assert mapping[section_id] == [0]


def test_link_russian_text() -> None:
    linker = ClaimLinker()
    claims = [
        _claim("Эпоха Просвещения изменила европейскую философию и науку радикально."),
    ]
    outline = _outline_with_keys(
        [("Введение", ["Просвещения европейскую философию науку"])],
    )

    mapping = linker.link_claims_to_sections(claims, outline)

    section_id = str(outline.sections[0].id)
    assert mapping[section_id] == [0]


def test_stopwords_filtered() -> None:
    linker = ClaimLinker()
    claims = [_claim("The importance of renewable energy in modern society today.")]
    outline = _outline_with_keys(
        [("Body", ["renewable energy significance"])],
    )

    mapping = linker.link_claims_to_sections(claims, outline)

    section_id = str(outline.sections[0].id)
    assert mapping[section_id] == [0]


def test_empty_claims_returns_empty() -> None:
    linker = ClaimLinker()
    outline = _outline_with_keys([("Body", ["something"])])

    mapping = linker.link_claims_to_sections([], outline)

    assert all(indices == [] for indices in mapping.values())


def test_empty_outline_keys_does_not_match() -> None:
    linker = ClaimLinker()
    outline = ArticleOutline(
        title="Empty outline",
        structure=ArticleStructure.REFERAT,
        sections=[
            OutlineSection(
                title="Body",
                target_words=300,
                key_claims_to_use=[],
                purpose="Body of the article",
            )
        ],
        thesis="A thesis statement long enough to satisfy the model.",
        total_target_words=300,
    )
    claims = [_claim("Some claim about a topic that does not match.")]

    mapping = linker.link_claims_to_sections(claims, outline)

    section_id = str(outline.sections[0].id)
    assert section_id not in mapping or mapping[section_id] == []


_ = uuid4  # keep import for future fixtures
