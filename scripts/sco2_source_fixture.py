"""sCO2 regression source fixture — the technical, chart-heavy, no-people deck.

This module provides the **source-side** fixture (interview + chunks + claims +
metadata) for the Phase 2 deck-vs-plan regression, built from a REAL paper:

    "Re-Architecting Data Centers as Thermodynamic Systems —
     A Supercritical CO2 Cooling and Energy Recovery Framework"

The chunk text below is transcribed faithfully from that paper (uploaded as
``document_pdf.pdf``); it is NOT fabricated and NOT paraphrased. It is the same
source the editorial DATA-SHAPE → ENCODING examples were drawn from (PUE 1.08
vs 1.55, rack densities 25-30 / 100 / 300 kW, $1.04M per MW, 3.2-year payback,
the Brayton-cycle recovery, Table 1).

WHY THIS IS THE REGRESSION FIXTURE
----------------------------------
Phase 2 binds editorial to a source-grounded :class:`DeckPlan` and adds a
deck-vs-plan validator. The Enlightenment fixture proves the *positive* case
(real thinkers appear; Bach + Mozart, not Beethoven). THIS fixture proves the
*negative* case, which is just as load-bearing for the no-hardcode rule:

* The paper is dense with quantitative data — PUE, rack-density spread, an
  energy-split, capital cost, payback, the cooling-tech comparison table — so
  the DATA-SHAPE → ENCODING tree must keep choosing charts/stats correctly.
* The paper names **no biographical figures**. The only proper names in it are
  bibliographic (``Ahn, Y. et al.`` in the references). A correct planner must
  therefore return an **empty (or near-empty) ``figures`` roster**, and the
  deck must grow **no GALLERY_PEOPLE slide** — there is no minimum-people
  quota to fill. A deck that sprouts a fabricated people slide here is the
  exact hardcoded-quota failure Phase 2 forbids.

The fixture mirrors :func:`scripts.proof_planner_phase1._build_fixture` in
shape so the Phase 2 harness and the unit tests can both import it:

    from scripts.sco2_source_fixture import build_sco2_source_fixture
    interview, chunks, claims, metadata = build_sco2_source_fixture()

Run this module directly to self-verify (construct + round-trip + bounds):

    python scripts/sco2_source_fixture.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repo importable when running this file directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.core.enums import (  # noqa: E402
    AudienceType,
    ClaimStrength,
    ClaimType,
    Language,
    NarrativeEmphasis,
    TitleStyle,
)
from packages.core.models.presentation import PresentationInterviewAnswers  # noqa: E402
from packages.core.models.source import (  # noqa: E402
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)

# ---------------------------------------------------------------------------
# Source chunks — verbatim from the paper, split by section. Page numbers
# match the source PDF (3 pages). Text is transcribed, not summarised.
# ---------------------------------------------------------------------------


_CHUNK_0_ABSTRACT = (
    "Re-Architecting Data Centers as Thermodynamic Systems\n"
    "A Supercritical CO2 Cooling and Energy Recovery Framework\n\n"
    "Abstract\n"
    "The rapid expansion of artificial intelligence workloads has exposed critical "
    "limitations in conventional data center cooling infrastructure. Current systems, "
    "whether air-cooled or liquid-cooled, address thermal challenges at isolated levels, "
    "producing fragmented designs with limited scalability. This paper proposes a "
    "multi-level cooling architecture based on supercritical carbon dioxide (sCO2), "
    "designed to operate cohesively across chip, rack, and facility scales. The framework "
    "achieves a Power Usage Effectiveness (PUE) of 1.08 compared to 1.55 for conventional "
    "air cooling, eliminates water consumption entirely, and enables energy recovery of "
    "5-20% of waste heat through an integrated Brayton cycle. Capital cost is estimated at "
    "$1.04M per MW of cooling capacity with a payback period of 3.2 years."
)


_CHUNK_1_INTRODUCTION = (
    "1. Introduction\n"
    "Data centers consume approximately 560 billion liters of water annually for cooling "
    "operations. Traditional air cooling systems are fundamentally constrained to 25-30 kW "
    "per rack, while modern AI training clusters routinely exceed 100 kW per rack, with "
    "projections indicating 1 MW per rack within the next decade. This mismatch between "
    "compute density and thermal management capability has made cooling, not computation, "
    "the primary bottleneck to scaling data center infrastructure.\n\n"
    "A system-level analysis reveals that approximately 65% of total facility energy is "
    "consumed by IT workloads, while 35% is lost to infrastructure overhead. Cooling alone "
    "accounts for 22% of total facility energy and 63% of all overhead energy. The "
    "industry-average PUE of 1.56-1.58 means that for every 1 MW of compute delivered, "
    "approximately 0.56 MW is spent on supporting infrastructure, primarily thermal "
    "management."
)


_CHUNK_2_LIMITATIONS = (
    "2. Limitations of Current Cooling Approaches\n"
    "Air cooling, the dominant paradigm in existing facilities, encounters severe physical "
    "limits above 30 kW per rack. Beyond this threshold, cooling efficiency drops sharply, "
    "fan energy consumption increases non-linearly, and thermal hotspot formation becomes "
    "unmanageable. At higher rack densities, systems become thermally unstable, noise "
    "levels exceed 80 dB, and cooling overhead scales disproportionately to compute gains.\n\n"
    "Liquid cooling technologies provide meaningful improvements, achieving up to 66% "
    "reduction in cooling energy and enabling rack densities above 100 kW. However, "
    "significant limitations persist: increased system complexity, substantial pumping and "
    "distribution overhead, persistent facility-level inefficiencies, and a fundamental "
    "lack of integration across system layers. Even hybrid cooling configurations deliver "
    "only 25-30% total facility energy reduction, far short of what next-generation compute "
    "densities require."
)


_CHUNK_3_TABLE_AND_FLUID = (
    "Table 1: Cooling Technology Comparison\n"
    "Parameter | Air Cooling | Liquid Cooling | sCO2 (Proposed)\n"
    "Max Rack Density | 25-30 kW | 100 kW | 300 kW\n"
    "PUE | 1.55-1.80 | 1.20-1.30 | 1.08\n"
    "Cooling Energy Reduction | Baseline | 66% | 85%\n"
    "Water Consumption | High | Moderate | Zero\n"
    "Energy Recovery | None | None | 5-20%\n"
    "Capital Cost (per MW) | $0.6M | $0.8M | $1.04M\n"
    "Payback Period | N/A | 4-6 years | 3.2 years\n\n"
    "3. Supercritical CO2 as a Working Fluid\n"
    "Supercritical CO2 operates above its critical point at 31 degrees Celsius and 73.8 "
    "bar, where it exhibits a unique combination of liquid-like density for high heat "
    "absorption capacity and gas-like viscosity for efficient pumping. Near the critical "
    "point, the specific heat of CO2 spikes dramatically, enabling the fluid to absorb "
    "large quantities of thermal energy with minimal temperature rise. This pseudo-critical "
    "behavior is the thermodynamic foundation that makes sCO2 superior to both water and "
    "air as a cooling medium for high-density compute environments.\n\n"
    "The key thermophysical properties include: high density enabling high heat capacity "
    "per unit volume, low viscosity requiring minimal pumping power, single-phase operation "
    "eliminating boiling instability, and high compressibility enabling efficient energy "
    "recovery through expansion cycles. Unlike water-based cooling, the system operates as "
    "a fully closed loop with zero water consumption and no risk of leakage damage to "
    "electronic components."
)


_CHUNK_4_ARCHITECTURE = (
    "4. Multi-Level Architecture\n"
    "The proposed system operates as an integrated cooling loop across three scales. At the "
    "chip level, microchannel cold plates fabricated in copper or nickel-plated substrate "
    "contain channels at 100-300 micrometer scale. Cold sCO2 enters at 80-100 bar and 30-40 "
    "degrees Celsius, absorbs heat through the massive surface area of the microchannel "
    "network, and exits at 50-65 degrees Celsius while remaining in a single supercritical "
    "phase. This eliminates vapor bubble formation and the associated thermal instabilities "
    "that plague two-phase cooling systems.\n\n"
    "At the rack level, the system transitions from localized heat extraction to "
    "distributed thermal aggregation. A parallel flow configuration ensures each compute "
    "node receives coolant at uniform inlet temperature, preventing the thermal gradient "
    "buildup that occurs in series configurations. Primary supply and return headers "
    "operate at 80-120 bar with minimal pressure drop, while secondary distribution "
    "manifolds provide precision flow balancing to each chip-level cold plate.\n\n"
    "At the facility level, waste heat collected from the rack-level return headers drives "
    "a supercritical CO2 Brayton cycle. The heated fluid expands through a turbine, "
    "producing mechanical work that can be converted to electrical energy, recovering 5-20% "
    "of the total waste heat. The expanded fluid then passes through a dry cooler for heat "
    "rejection before recompression completes the thermodynamic loop."
)


_CHUNK_5_RESULTS_CONCLUSION = (
    "5. Results and Performance Analysis\n"
    "System modeling indicates a target PUE of 1.08, representing a 30% improvement over "
    "best-in-class liquid cooling systems (PUE 1.20) and a 44% improvement over "
    "industry-average air cooling (PUE 1.55). For a 10 MW IT load facility, the proposed "
    "architecture reduces total facility power from 15.5 MW (air-cooled) to 10.8 MW, "
    "yielding annual energy savings of approximately $4.1 million at $0.10 per kWh. The "
    "elimination of water consumption removes approximately 56 million liters of annual "
    "water usage per 10 MW facility.\n\n"
    "The Brayton cycle energy recovery subsystem generates approximately 0.5-2 MW of "
    "electrical output from a 10 MW IT load facility, depending on turbine efficiency and "
    "heat source temperature. At conservative estimates, this represents $0.4-1.6 million "
    "in additional annual value. Combined with cooling energy savings, the total economic "
    "benefit yields a capital payback period of 3.2 years for the complete system "
    "deployment.\n\n"
    "6. Conclusion\n"
    "The supercritical CO2 multi-level cooling framework represents a fundamental shift "
    "from incremental cooling improvements to holistic thermal system redesign. By unifying "
    "heat extraction, transport, and recovery into a single closed-loop architecture, the "
    "system achieves performance metrics that are unattainable through conventional "
    "approaches. The framework is particularly relevant for next-generation AI training "
    "facilities where rack densities will exceed 300 kW and water availability constraints "
    "increasingly limit site selection options.\n\n"
    "References\n"
    "1. Uptime Institute. Global Data Center Survey 2024. Annual Report, 2024.\n"
    "2. ASME Journal of Thermal Science and Engineering Applications, Vol. 146, Issue 3, "
    "2024.\n"
    "3. U.S. Department of Energy. Data Center Energy Efficiency Report. Technical Report "
    "DOE/EE-2023, 2023.\n"
    "4. International Energy Agency. Data Centres and Data Transmission Networks. IEA "
    "Report, 2024.\n"
    "5. Ahn, Y. et al. Review of supercritical CO2 power cycle technology. Nuclear "
    "Engineering and Technology, 47(6), 647-661, 2015."
)


# (chunk_index, page, text) — page numbers follow the source PDF layout.
_CHUNKS: tuple[tuple[int, int, str], ...] = (
    (0, 1, _CHUNK_0_ABSTRACT),
    (1, 1, _CHUNK_1_INTRODUCTION),
    (2, 1, _CHUNK_2_LIMITATIONS),
    (3, 2, _CHUNK_3_TABLE_AND_FLUID),
    (4, 2, _CHUNK_4_ARCHITECTURE),
    (5, 3, _CHUNK_5_RESULTS_CONCLUSION),
)


# ---------------------------------------------------------------------------
# Extracted claims — a representative slice the claim extractor would emit.
# Intentionally thin (the planner reads the chunks above as ground truth);
# broad type coverage so the DATA-SHAPE → ENCODING tree is exercised.
# (claim_text, claim_type, strength, quote)
# ---------------------------------------------------------------------------


_CLAIMS: tuple[tuple[str, ClaimType, ClaimStrength, str | None], ...] = (
    (
        "The sCO2 framework achieves a Power Usage Effectiveness of 1.08, versus 1.55 for "
        "conventional air cooling.",
        ClaimType.STATISTICAL_RESULT,
        ClaimStrength.STRONG,
        "a Power Usage Effectiveness (PUE) of 1.08 compared to 1.55 for conventional air cooling",
    ),
    (
        "Maximum rack density rises from 25-30 kW for air cooling to 100 kW for liquid "
        "cooling to 300 kW for sCO2.",
        ClaimType.COMPARISON,
        ClaimStrength.STRONG,
        "Max Rack Density | 25-30 kW | 100 kW | 300 kW",
    ),
    (
        "Capital cost is estimated at $1.04M per MW of cooling capacity with a payback "
        "period of 3.2 years.",
        ClaimType.STATISTICAL_RESULT,
        ClaimStrength.STRONG,
        "$1.04M per MW of cooling capacity with a payback period of 3.2 years",
    ),
    (
        "Cooling alone accounts for 22% of total facility energy and 63% of all overhead energy.",
        ClaimType.EMPIRICAL_FINDING,
        ClaimStrength.STRONG,
        "Cooling alone accounts for 22% of total facility energy and 63% of all overhead energy",
    ),
    (
        "Roughly 65% of total facility energy is consumed by IT workloads while 35% is lost "
        "to infrastructure overhead.",
        ClaimType.EMPIRICAL_FINDING,
        ClaimStrength.MODERATE,
        "approximately 65% of total facility energy is consumed by IT workloads, while 35% "
        "is lost to infrastructure overhead",
    ),
    (
        "Data centers consume approximately 560 billion liters of water annually for cooling "
        "operations.",
        ClaimType.STATISTICAL_RESULT,
        ClaimStrength.MODERATE,
        "approximately 560 billion liters of water annually for cooling operations",
    ),
    (
        "Cooling, not computation, has become the primary bottleneck to scaling data center "
        "infrastructure.",
        ClaimType.THEORETICAL_ARGUMENT,
        ClaimStrength.STRONG,
        "made cooling, not computation, the primary bottleneck to scaling data center "
        "infrastructure",
    ),
    (
        "Near its critical point of 31 degrees Celsius and 73.8 bar, the specific heat of "
        "CO2 spikes, absorbing large thermal energy with minimal temperature rise.",
        ClaimType.THEORETICAL_ARGUMENT,
        ClaimStrength.MODERATE,
        "Near the critical point, the specific heat of CO2 spikes dramatically",
    ),
    (
        "Chip-level microchannel cold plates take sCO2 in at 80-100 bar and 30-40C and "
        "exhaust it at 50-65C in a single supercritical phase.",
        ClaimType.METHODOLOGICAL,
        ClaimStrength.MODERATE,
        "enters at 80-100 bar and 30-40 degrees Celsius ... exits at 50-65 degrees Celsius "
        "while remaining in a single supercritical phase",
    ),
    (
        "A facility-level supercritical CO2 Brayton cycle recovers 5-20% of waste heat as "
        "electrical output.",
        ClaimType.METHODOLOGICAL,
        ClaimStrength.MODERATE,
        "drives a supercritical CO2 Brayton cycle ... recovering 5-20% of the total waste heat",
    ),
    (
        "For a 10 MW IT load facility the design cuts total facility power from 15.5 MW to "
        "10.8 MW, saving about $4.1 million per year.",
        ClaimType.STATISTICAL_RESULT,
        ClaimStrength.MODERATE,
        "reduces total facility power from 15.5 MW (air-cooled) to 10.8 MW, yielding annual "
        "energy savings of approximately $4.1 million",
    ),
    (
        "Air cooling hits severe physical limits above 30 kW per rack, with noise exceeding "
        "80 dB at higher densities.",
        ClaimType.LIMITATION,
        ClaimStrength.MODERATE,
        "severe physical limits above 30 kW per rack ... noise levels exceed 80 dB",
    ),
    (
        "Even hybrid cooling configurations deliver only 25-30% total facility energy "
        "reduction, short of next-generation needs.",
        ClaimType.LIMITATION,
        ClaimStrength.MODERATE,
        "hybrid cooling configurations deliver only 25-30% total facility energy reduction",
    ),
)


_SOURCE_TITLE = (
    "Re-Architecting Data Centers as Thermodynamic Systems: A Supercritical CO2 Cooling "
    "and Energy Recovery Framework"
)


def build_sco2_source_fixture() -> tuple[
    PresentationInterviewAnswers,
    list[SourceChunkCreate],
    list[SourceClaimCreate],
    list[SourceMetadataExtracted],
]:
    """Return (interview, chunks, claims, metadata) for the sCO2 regression.

    The interview asks for a results-forward technical deck for a mixed
    academic/industry audience in English, foregrounding the headline figures
    the paper leads with (PUE, the cooling-energy reduction, the payback). It
    leaves interactivity OFF: this fixture exists to exercise chart selection
    and the no-fabricated-people guarantee, not the interactive pass.
    """

    interview = PresentationInterviewAnswers(
        audience=AudienceType.MIXED_ACADEMIC_INDUSTRY,
        language=Language.EN,
        narrative_emphasis=NarrativeEmphasis.RESULTS_NUMBERS,
        title_style=TitleStyle.TAKEAWAY,
        include_interactive=False,
        headline_numbers=["PUE 1.08 vs 1.55", "85% cooling-energy cut", "3.2-year payback"],
        closing_ask=(
            "Should hyperscale operators commit to supercritical CO2 cooling for their "
            "next-generation AI training facilities?"
        ),
    )

    chunks = [
        SourceChunkCreate(chunk_index=index, page=page, text=text) for index, page, text in _CHUNKS
    ]

    claims = [
        SourceClaimCreate(
            claim_text=claim_text,
            claim_type=claim_type,
            strength=strength,
            quote=quote,
        )
        for claim_text, claim_type, strength, quote in _CLAIMS
    ]

    metadata = [
        SourceMetadataExtracted(
            title=_SOURCE_TITLE,
            # The paper carries no author byline and states no publication year
            # of its own; faithfully leave both empty rather than inventing them.
            authors=[],
            year=None,
            page_count=3,
            word_count=sum(len(text.split()) for _, _, text in _CHUNKS),
            language_detected="en",
            has_images=False,
        ),
    ]

    return interview, chunks, claims, metadata


def _self_check() -> int:
    """Construct, round-trip, and summarise the fixture. Exit 0 on success."""

    interview, chunks, claims, metadata = build_sco2_source_fixture()

    # Round-trip every model: dump to dict, reconstruct, assert equality. This
    # is the core-models rule (serialise + reconstruct without data loss).
    for model in (interview, *chunks, *claims, *metadata):
        reconstructed = type(model).model_validate(model.model_dump())
        if reconstructed != model:
            print(f"FAIL round-trip: {type(model).__name__}")
            return 1

    total_chars = sum(len(c.text) for c in chunks)
    longest = max(len(c.text) for c in chunks)
    by_type: dict[str, int] = {}
    for claim in claims:
        by_type[claim.claim_type.value] = by_type.get(claim.claim_type.value, 0) + 1

    print("sCO2 source fixture - self-check")
    print("=" * 60)
    print(
        f"  interview: {interview.audience.value} / {interview.language.value} / "
        f"emphasis={interview.narrative_emphasis.value} / interactive={interview.include_interactive}"
    )
    print(f"  headline_numbers: {interview.headline_numbers}")
    print(f"  chunks: {len(chunks)}  (total {total_chars} chars, longest {longest}, cap 10000)")
    print(f"  claims: {len(claims)}  by type: {by_type}")
    meta = metadata[0]
    print(
        f"  metadata: title set={meta.title is not None}, authors={meta.authors}, "
        f"year={meta.year}, pages={meta.page_count}, words={meta.word_count}, "
        f"lang={meta.language_detected}"
    )
    print()
    print("  Regression expectation (verified later on Vertex, not asserted here):")
    print("   - planner figures roster is EMPTY (the source names no biographical people)")
    print("   - deck grows NO GALLERY_PEOPLE slide (no minimum-people quota to fill)")
    print("   - charts/stats still chosen by the DATA-SHAPE tree")
    print()
    print("OK - fixture constructs, respects all field bounds, and round-trips.")
    return 0


if __name__ == "__main__":
    sys.exit(_self_check())
