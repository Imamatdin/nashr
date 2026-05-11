"""Behaviour tests for :mod:`packages.bot.states`.

The FSM state groups are the contract every handler subscribes to.
Each test pins the set of states a group must expose; renaming or
removing one would shift filter behaviour silently otherwise.
"""

from __future__ import annotations

from aiogram.fsm.state import State

from packages.bot.states import (
    ArticleStates,
    PaymentStates,
    PresentationStates,
    RegistrationStates,
)


def _state_names(group: type) -> set[str]:
    return {
        name
        for name, value in vars(group).items()
        if isinstance(value, State) and not name.startswith("_")
    }


def test_registration_states_exist() -> None:
    assert _state_names(RegistrationStates) == {
        "choosing_language",
        "choosing_calibration",
        "entering_name",
        "confirming",
    }


def test_article_states_exist() -> None:
    assert _state_names(ArticleStates) == {
        "uploading_sources",
        "waiting_for_more_sources",
        "answering_interview",
        "reviewing_outline",
        "choosing_tier",
        "confirming_payment",
        "generating",
        "reviewing_output",
    }


def test_presentation_states_exist() -> None:
    assert _state_names(PresentationStates) == {
        "uploading_sources",
        "waiting_for_more_sources",
        "opening_mini_app",
        "waiting_for_mini_app",
        "choosing_tier",
        "confirming_payment",
        "generating",
        "reviewing_output",
    }


def test_payment_states_exist() -> None:
    assert _state_names(PaymentStates) == {
        "choosing_provider",
        "waiting_for_payment",
    }


def test_state_instances_are_state_objects() -> None:
    """Sanity check: each attribute really is an aiogram ``State`` instance."""

    assert isinstance(RegistrationStates.choosing_language, State)
    assert isinstance(ArticleStates.uploading_sources, State)
    assert isinstance(PresentationStates.opening_mini_app, State)
    assert isinstance(PaymentStates.choosing_provider, State)


def test_groups_have_unique_state_identifiers() -> None:
    """Two groups must not collide on the qualified state string aiogram emits."""

    reg_state = RegistrationStates.choosing_language.state
    art_state = ArticleStates.uploading_sources.state
    pres_state = PresentationStates.uploading_sources.state
    pay_state = PaymentStates.choosing_provider.state
    assert len({reg_state, art_state, pres_state, pay_state}) == 4
