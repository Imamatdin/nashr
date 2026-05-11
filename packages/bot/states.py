"""FSM state groups for every conversation flow the bot supports.

Each high-level flow (registration, article creation, presentation
creation, payment) owns its own ``StatesGroup``. aiogram's FSM tracks
the user's position via these states so handlers can be filtered by
state and only fire at the right point in a conversation.

The state values themselves carry no payload; flow data (project_id,
language, uploaded source list, chosen tier) is stored in the FSM's
context dict via ``state.update_data``.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """New-user onboarding: language → calibration → name → confirm."""

    choosing_language = State()
    choosing_calibration = State()
    entering_name = State()
    confirming = State()


class ArticleStates(StatesGroup):
    """Article creation funnel.

    The interview/outline/generation stages are scaffolded here; the
    actual pipeline wiring (calling the interview engine, outline
    generator, drafter) lands in Task 27.
    """

    uploading_sources = State()
    waiting_for_more_sources = State()
    answering_interview = State()
    reviewing_outline = State()
    choosing_tier = State()
    confirming_payment = State()
    generating = State()
    reviewing_output = State()


class PresentationStates(StatesGroup):
    """Presentation creation funnel.

    Differs from the article flow in that the research interview is
    replaced by a Mini App questionnaire; ``opening_mini_app`` is the
    state while the Mini App button is on screen, and
    ``waiting_for_mini_app`` is set once the user has tapped it.
    """

    uploading_sources = State()
    waiting_for_more_sources = State()
    opening_mini_app = State()
    waiting_for_mini_app = State()
    choosing_tier = State()
    confirming_payment = State()
    generating = State()
    reviewing_output = State()


class PaymentStates(StatesGroup):
    """Shared payment flow used by both article and presentation funnels."""

    choosing_provider = State()
    waiting_for_payment = State()
