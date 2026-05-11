"""Registration funnel: language → calibration → name → main menu.

Each step is a callback or message handler filtered by an FSM state so
the user can only advance once the previous step has fired. The
collected values are stored in the FSM data dict; the final step
persists the user via :meth:`DatabaseClient.create_user` and clears
the FSM.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from packages.bot.keyboards import calibration_keyboard, main_menu_keyboard
from packages.bot.labels import get_bot_labels
from packages.bot.states import RegistrationStates
from packages.platform.database import DatabaseClient

router = Router()

_VALID_LANGUAGES = {"uz", "ru", "en", "kaa"}
_VALID_CALIBRATIONS = {"school", "bakalavr", "magistratura", "doctoral"}


@router.callback_query(RegistrationStates.choosing_language, F.data.startswith("lang_"))
async def process_language(callback: CallbackQuery, state: FSMContext, db: DatabaseClient) -> None:
    """Persist the chosen language in FSM data and ask for calibration."""

    raw = callback.data or ""
    lang = raw.removeprefix("lang_")
    if lang not in _VALID_LANGUAGES:
        await callback.answer()
        return
    await state.update_data(language=lang)

    labels = get_bot_labels(lang)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            labels.choose_calibration,
            reply_markup=calibration_keyboard(lang),
        )
    await state.set_state(RegistrationStates.choosing_calibration)
    await callback.answer()


@router.callback_query(RegistrationStates.choosing_calibration, F.data.startswith("cal_"))
async def process_calibration(callback: CallbackQuery, state: FSMContext) -> None:
    """Persist calibration level and prompt for the user's name."""

    raw = callback.data or ""
    calibration = raw.removeprefix("cal_")
    if calibration not in _VALID_CALIBRATIONS:
        await callback.answer()
        return
    data = await state.get_data()
    lang = str(data.get("language", "uz"))

    await state.update_data(calibration=calibration)

    labels = get_bot_labels(lang)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(labels.enter_name)
    await state.set_state(RegistrationStates.entering_name)
    await callback.answer()


@router.message(RegistrationStates.entering_name)
async def process_name(message: Message, state: FSMContext, db: DatabaseClient) -> None:
    """Final step: insert the user row and show the main menu."""

    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    lang = str(data.get("language", "uz"))
    calibration = str(data.get("calibration", "bakalavr"))
    name = message.text.strip()

    user = await db.create_user(
        telegram_id=message.from_user.id,
        language=lang,
        calibration_level=calibration,
        full_name=name,
    )

    labels = get_bot_labels(lang)
    subscriber_id = user.get("subscriber_id", "")

    await message.answer(
        f"{labels.registration_complete}\n\nID: <b>{subscriber_id}</b>",
    )
    await message.answer(labels.main_menu, reply_markup=main_menu_keyboard(lang))
    await state.clear()
