"""Inline-keyboard factories for the Telegram bot.

Every keyboard is built fresh per request: aiogram's
``InlineKeyboardMarkup`` objects are simple data containers, so the
small cost of reconstruction is worth never having to worry about
cross-user mutation of a shared instance. Button text comes from the
localized :class:`packages.bot.labels.BotLabels` pack — handlers pass
the user's language code and the keyboard picks the right strings.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from packages.bot.labels import get_bot_labels


def language_keyboard() -> InlineKeyboardMarkup:
    """Language picker shown on first ``/start``.

    Hardcoded button labels because the user has not yet chosen a
    language — every other keyboard is localized via ``get_bot_labels``.
    """

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="O'zbekcha 🇺🇿", callback_data="lang_uz"),
                InlineKeyboardButton(text="Русский 🇷🇺", callback_data="lang_ru"),
            ],
            [
                InlineKeyboardButton(text="Qaraqalpaqsha", callback_data="lang_kaa"),
                InlineKeyboardButton(text="English 🇬🇧", callback_data="lang_en"),
            ],
        ]
    )


def calibration_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Education-level picker shown during registration."""

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=labels.calibration_school, callback_data="cal_school")],
            [InlineKeyboardButton(text=labels.calibration_bachelor, callback_data="cal_bakalavr")],
            [
                InlineKeyboardButton(
                    text=labels.calibration_master, callback_data="cal_magistratura"
                )
            ],
            [InlineKeyboardButton(text=labels.calibration_doctoral, callback_data="cal_doctoral")],
        ]
    )


def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Top-level menu shown after registration and from ``/start``."""

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=labels.create_article, callback_data="create_article")],
            [
                InlineKeyboardButton(
                    text=labels.create_presentation, callback_data="create_presentation"
                )
            ],
            [InlineKeyboardButton(text=labels.my_projects, callback_data="my_projects")],
            [InlineKeyboardButton(text=labels.my_balance, callback_data="my_balance")],
            [InlineKeyboardButton(text=labels.settings, callback_data="settings")],
        ]
    )


def upload_more_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Shown after each successful upload: 'add more' or 'continue'."""

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=labels.upload_more, callback_data="upload_more")],
            [InlineKeyboardButton(text=labels.continue_btn, callback_data="continue_flow")],
        ]
    )


def outline_review_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Approve / regenerate / cancel buttons under a generated outline."""

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=labels.approve, callback_data="approve_outline")],
            [InlineKeyboardButton(text=labels.regenerate, callback_data="regenerate_outline")],
            [InlineKeyboardButton(text=labels.cancel, callback_data="cancel_flow")],
        ]
    )


def tier_keyboard(lang: str, product: str) -> InlineKeyboardMarkup:
    """Pricing-tier picker. ``product`` is ``article`` or ``presentation``.

    Prices are hardcoded to match
    :class:`packages.platform.credits.CreditLedger.PRICING`; if those
    change, update both. The thousand-separator format is preserved as
    a literal so users see the familiar Uzbek/Russian comma grouping.
    """

    labels = get_bot_labels(lang)
    if product == "article":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{labels.basic} — 60,000 UZS", callback_data="tier_basic"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{labels.standard} — 90,000 UZS", callback_data="tier_standard"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{labels.premium} — 150,000 UZS", callback_data="tier_premium"
                    )
                ],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{labels.basic} — 5,000 UZS", callback_data="tier_basic")],
            [
                InlineKeyboardButton(
                    text=f"{labels.standard} — 10,000 UZS", callback_data="tier_standard"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{labels.premium} — 15,000 UZS", callback_data="tier_premium"
                )
            ],
        ]
    )


def payment_provider_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Payment-provider picker. Balance is the fourth option, on its own row."""

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Payme", callback_data="pay_payme")],
            [InlineKeyboardButton(text="Click", callback_data="pay_click")],
            [InlineKeyboardButton(text="Uzum", callback_data="pay_uzum")],
            [InlineKeyboardButton(text=labels.use_balance, callback_data="pay_balance")],
        ]
    )


def output_review_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Article delivery keyboard: download formats, regenerate, done.

    DOCX and PDF live on the same row so the two main formats fit in
    one tap-target line. PPTX is article-irrelevant; see
    :func:`presentation_output_keyboard` for the presentation variant.
    """

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 DOCX", callback_data="download_docx"),
                InlineKeyboardButton(text="📑 PDF", callback_data="download_pdf"),
            ],
            [InlineKeyboardButton(text=labels.regenerate, callback_data="regenerate_output")],
            [InlineKeyboardButton(text=labels.done, callback_data="done")],
        ]
    )


def presentation_output_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Presentation delivery keyboard: HTML / PPTX on top, PDF below."""

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🌐 HTML", callback_data="download_html"),
                InlineKeyboardButton(text="📊 PPTX", callback_data="download_pptx"),
            ],
            [InlineKeyboardButton(text="📑 PDF", callback_data="download_pdf")],
            [InlineKeyboardButton(text=labels.regenerate, callback_data="regenerate_output")],
            [InlineKeyboardButton(text=labels.done, callback_data="done")],
        ]
    )


def presentation_chat_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Downloads + done, shown after the brain re-delivers an edit (Stage 4).

    Deliberately OMITS the ``regenerate_output`` button of
    :func:`presentation_output_keyboard`: regeneration mid-conversation is the
    brain's job (a fix), not a full pipeline re-run, and that handler is bound to
    ``reviewing_output`` anyway. ``done`` ends the editing conversation.
    """

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🌐 HTML", callback_data="download_html"),
                InlineKeyboardButton(text="📊 PPTX", callback_data="download_pptx"),
            ],
            [InlineKeyboardButton(text="📑 PDF", callback_data="download_pdf")],
            [InlineKeyboardButton(text=labels.done, callback_data="done")],
        ]
    )


def presentation_approval_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Approve / reject buttons for the brain's code-side approval gate.

    The user pressing approve is the ONLY thing that authorizes a gated
    re-delivering change — the model can never synthesize this callback, which is
    what makes the gate code-side rather than model-self-granted (Build 2,
    Stage 4).
    """

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=labels.approval_approve, callback_data="approve_redeliver"
                ),
                InlineKeyboardButton(text=labels.approval_reject, callback_data="reject_redeliver"),
            ]
        ]
    )


def presentation_mini_app_keyboard(lang: str, mini_app_url: str) -> InlineKeyboardMarkup:
    """Button that opens the presentation questionnaire Mini App.

    A second 'skip' button lets the user accept default settings and
    proceed without filling the questionnaire; the skip path is
    handled by :class:`PresentationInterviewEngine.apply_defaults`.
    """

    labels = get_bot_labels(lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=labels.open_questionnaire,
                    web_app=WebAppInfo(url=mini_app_url),
                )
            ],
            [
                InlineKeyboardButton(
                    text=labels.skip_questionnaire, callback_data="skip_questionnaire"
                )
            ],
        ]
    )
