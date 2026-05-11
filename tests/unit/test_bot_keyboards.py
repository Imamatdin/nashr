"""Behaviour tests for :mod:`packages.bot.keyboards`.

Each test inspects the constructed ``InlineKeyboardMarkup`` for the
properties the rest of the bot depends on: button count, callback
identifiers, price strings, language-driven label changes, and
Mini App ``web_app`` attachment.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from packages.bot.keyboards import (
    calibration_keyboard,
    language_keyboard,
    main_menu_keyboard,
    outline_review_keyboard,
    output_review_keyboard,
    payment_provider_keyboard,
    presentation_mini_app_keyboard,
    presentation_output_keyboard,
    tier_keyboard,
    upload_more_keyboard,
)


def _all_buttons(kb: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    return [btn for row in kb.inline_keyboard for btn in row]


def _all_callback_data(kb: InlineKeyboardMarkup) -> list[str]:
    return [btn.callback_data for btn in _all_buttons(kb) if btn.callback_data is not None]


def _all_texts(kb: InlineKeyboardMarkup) -> list[str]:
    return [btn.text for btn in _all_buttons(kb)]


def test_language_keyboard_has_4_options() -> None:
    kb = language_keyboard()
    callbacks = _all_callback_data(kb)
    assert sorted(callbacks) == ["lang_en", "lang_kaa", "lang_ru", "lang_uz"]


def test_language_keyboard_button_texts() -> None:
    kb = language_keyboard()
    texts = _all_texts(kb)
    assert any("O'zbekcha" in t for t in texts)
    assert any("Русский" in t for t in texts)
    assert any("Qaraqalpaqsha" in t for t in texts)
    assert any("English" in t for t in texts)


def test_calibration_keyboard_has_4_levels() -> None:
    kb = calibration_keyboard("uz")
    callbacks = _all_callback_data(kb)
    assert sorted(callbacks) == ["cal_bakalavr", "cal_doctoral", "cal_magistratura", "cal_school"]


def test_main_menu_keyboard_has_5_options() -> None:
    kb = main_menu_keyboard("uz")
    callbacks = _all_callback_data(kb)
    assert sorted(callbacks) == sorted(
        [
            "create_article",
            "create_presentation",
            "my_projects",
            "my_balance",
            "settings",
        ]
    )


def test_upload_more_keyboard_callbacks() -> None:
    kb = upload_more_keyboard("uz")
    callbacks = _all_callback_data(kb)
    assert sorted(callbacks) == ["continue_flow", "upload_more"]


def test_outline_review_keyboard_callbacks() -> None:
    kb = outline_review_keyboard("uz")
    callbacks = _all_callback_data(kb)
    assert sorted(callbacks) == ["approve_outline", "cancel_flow", "regenerate_outline"]


def test_tier_keyboard_article_prices() -> None:
    kb = tier_keyboard("uz", "article")
    texts = _all_texts(kb)
    joined = " | ".join(texts)
    assert "60,000" in joined
    assert "90,000" in joined
    assert "150,000" in joined


def test_tier_keyboard_article_callbacks() -> None:
    kb = tier_keyboard("uz", "article")
    callbacks = _all_callback_data(kb)
    assert sorted(callbacks) == ["tier_basic", "tier_premium", "tier_standard"]


def test_tier_keyboard_presentation_prices() -> None:
    kb = tier_keyboard("uz", "presentation")
    texts = _all_texts(kb)
    joined = " | ".join(texts)
    assert "5,000" in joined
    assert "10,000" in joined
    assert "15,000" in joined


def test_tier_keyboard_presentation_callbacks() -> None:
    kb = tier_keyboard("ru", "presentation")
    callbacks = _all_callback_data(kb)
    assert sorted(callbacks) == ["tier_basic", "tier_premium", "tier_standard"]


def test_payment_provider_keyboard_has_4_options() -> None:
    kb = payment_provider_keyboard("uz")
    callbacks = _all_callback_data(kb)
    assert sorted(callbacks) == ["pay_balance", "pay_click", "pay_payme", "pay_uzum"]


def test_payment_provider_keyboard_texts() -> None:
    kb = payment_provider_keyboard("uz")
    texts = _all_texts(kb)
    assert "Payme" in texts
    assert "Click" in texts
    assert "Uzum" in texts


def test_output_review_keyboard_has_docx_pdf() -> None:
    kb = output_review_keyboard("uz")
    callbacks = _all_callback_data(kb)
    assert "download_docx" in callbacks
    assert "download_pdf" in callbacks
    assert "regenerate_output" in callbacks
    assert "done" in callbacks


def test_presentation_output_keyboard_has_html_pptx_pdf() -> None:
    kb = presentation_output_keyboard("uz")
    callbacks = _all_callback_data(kb)
    assert "download_html" in callbacks
    assert "download_pptx" in callbacks
    assert "download_pdf" in callbacks


def test_presentation_mini_app_has_web_app() -> None:
    url = "https://nashr.uz/mini-app"
    kb = presentation_mini_app_keyboard("uz", url)
    buttons = _all_buttons(kb)
    web_app_buttons = [b for b in buttons if b.web_app is not None]
    assert len(web_app_buttons) == 1
    assert web_app_buttons[0].web_app is not None
    assert web_app_buttons[0].web_app.url == url


def test_presentation_mini_app_has_skip_button() -> None:
    kb = presentation_mini_app_keyboard("uz", "https://nashr.uz/m")
    callbacks = _all_callback_data(kb)
    assert "skip_questionnaire" in callbacks


def test_keyboards_localized_uz_vs_ru() -> None:
    kb_uz = main_menu_keyboard("uz")
    kb_ru = main_menu_keyboard("ru")
    assert _all_texts(kb_uz) != _all_texts(kb_ru)


def test_keyboards_localized_uz_vs_en() -> None:
    kb_uz = main_menu_keyboard("uz")
    kb_en = main_menu_keyboard("en")
    assert _all_texts(kb_uz) != _all_texts(kb_en)


def test_calibration_keyboard_localized() -> None:
    kb_uz = calibration_keyboard("uz")
    kb_kaa = calibration_keyboard("kaa")
    uz_texts = _all_texts(kb_uz)
    kaa_texts = _all_texts(kb_kaa)
    assert any("Maktab" in t for t in uz_texts)
    assert any("Mektep" in t for t in kaa_texts)


def test_tier_keyboard_unknown_product_returns_presentation() -> None:
    """Defensive: any non-``article`` value falls into the presentation branch."""

    kb = tier_keyboard("uz", "something_else")
    texts = _all_texts(kb)
    joined = " | ".join(texts)
    assert "5,000" in joined
