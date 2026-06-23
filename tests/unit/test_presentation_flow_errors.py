"""Tests for presentation-flow failure routing — the content-critic honest message.

The handler renders an honest "couldn't ground some claims; you've been refunded"
message (instead of the generic step error) when the wrapped editorial failure is
the content critic's hard stop. The detection is the load-bearing logic.
"""

from __future__ import annotations

from packages.bot.handlers.presentation_flow import _is_content_grounding_failure
from packages.bot.orchestrators.article_orchestrator import _OrchestratorError
from packages.core.enums import AuditSeverity
from packages.core.models.presentation import AuditCheckResult
from packages.presentation.editorial import EditorialContentCriticError


def _critic_error() -> EditorialContentCriticError:
    return EditorialContentCriticError(
        [
            AuditCheckResult(
                check_id="C-FB",
                check_name="content_critic.fabrication",
                passed=False,
                severity=AuditSeverity.FAIL,
                message="A fabricated figure survived the repair.",
            )
        ]
    )


def test_detects_critic_error_as_orchestrator_original() -> None:
    # Production path: the orchestrator wraps the critic error as `.original`.
    wrapped = _OrchestratorError("editorial", _critic_error())
    assert _is_content_grounding_failure(wrapped) is True


def test_detects_critic_error_through_cause_chain() -> None:
    # Defensive: the critic error is only reachable via the __cause__ chain.
    wrapped = _OrchestratorError("editorial", ValueError("unrelated"))
    wrapped.__cause__ = _critic_error()
    assert _is_content_grounding_failure(wrapped) is True


def test_other_editorial_failure_is_not_a_grounding_failure() -> None:
    wrapped = _OrchestratorError("editorial", ValueError("boom"))
    assert _is_content_grounding_failure(wrapped) is False
