"""Per-session edit allowance (Build 2, Stage 4).

A chatty editing session must not run unboundedly — the SDK will not stop it, so
this code does. The cap is a fix COUNTER, not a dollar budget: a tier grants a
fixed NUMBER of edits, and the session refuses once they are spent. This replaced
a per-fix cost projection — a counter is an integer the model cannot influence,
with no estimate to be wrong (the projection went through three rounds of bound
bugs; the count cannot be exceeded).

The real per-fix cost is still surfaced (``FixAndRenderResult.estimated_cost_usd``)
and accumulated on the session for billing/analytics, but it does NOT gate.
"""

from __future__ import annotations

from packages.core.enums import GenerationPackage

# Per-session fix allowance by tier. PLACEHOLDER values: the real editing-allowance
# economics are a Stage 5 decision. The counter is independent of WHICH model does
# editorial (Sonnet or a future Gemini editorial seat), so these survive that
# migration unchanged.
SESSION_FIX_LIMITS: dict[GenerationPackage, int] = {
    GenerationPackage.PRESENTATION_PREMIUM: 3,
    GenerationPackage.PRESENTATION_STANDARD: 2,
    GenerationPackage.PRESENTATION_BASIC: 1,
}
# Any non-presentation tier (article tiers, the bundle) falls back to the floor
# rather than an unbounded session.
_DEFAULT_FIX_LIMIT: int = 1


def session_fix_limit(package: GenerationPackage) -> int:
    """The number of edits a session gets for its tier."""

    return SESSION_FIX_LIMITS.get(package, _DEFAULT_FIX_LIMIT)


def has_fixes_remaining(fixes_used: int, package: GenerationPackage) -> bool:
    """The pre-fix gate: True while the session still has an edit left.

    A pure integer comparison the model cannot influence — there is no projection
    to be wrong and no assumption for review to break. ``fixes_used`` is bumped
    only after a fix SUCCEEDS, so the count can never be exceeded.
    """

    return fixes_used < session_fix_limit(package)


def session_total_spend_usd(accumulated_cost_usd: float, accumulated_image_count: int) -> float:
    """Total ACTUAL spend recorded for analytics — NOT the cap (the cap is the
    fix counter). Kept because the real per-fix cost is already surfaced."""

    # Imported inside the function so the fix ALLOWANCE (which the API's
    # /pricing route reads) does not drag google.genai into the API process
    # just to name a per-image dollar figure only analytics uses.
    from packages.core.gemini_image import IMAGE_COST_USD

    return accumulated_cost_usd + accumulated_image_count * IMAGE_COST_USD
