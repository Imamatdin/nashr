"""Behaviour tests for :mod:`packages.bot.labels`.

The label module is the bot's translation layer; bugs here surface as
wrong-language text, missing placeholders, or empty buttons. Each
test asserts a single property of the label contract.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from packages.bot.labels import (
    LABELS_EN,
    LABELS_KAA,
    LABELS_RU,
    LABELS_UZ,
    BotLabels,
    get_bot_labels,
)


def test_get_bot_labels_uzbek() -> None:
    labels = get_bot_labels("uz")
    assert labels is LABELS_UZ
    assert "Nashr" in labels.welcome
    assert "Maqola" in labels.create_article


def test_get_bot_labels_russian() -> None:
    labels = get_bot_labels("ru")
    assert labels is LABELS_RU
    assert "Добро пожаловать" in labels.welcome
    assert "статью" in labels.create_article


def test_get_bot_labels_english() -> None:
    labels = get_bot_labels("en")
    assert labels is LABELS_EN
    assert "Welcome" in labels.welcome
    assert "Create article" in labels.create_article


def test_get_bot_labels_karakalpak() -> None:
    labels = get_bot_labels("kaa")
    assert labels is LABELS_KAA
    assert "Nashr" in labels.welcome
    assert labels.approve == "✅ Tastıyıqlaw"


def test_get_bot_labels_unknown_falls_back_to_uzbek() -> None:
    assert get_bot_labels("xx") is LABELS_UZ
    assert get_bot_labels("") is LABELS_UZ
    assert get_bot_labels("zz_ZZ") is LABELS_UZ


def test_get_bot_labels_case_insensitive() -> None:
    assert get_bot_labels("RU") is LABELS_RU
    assert get_bot_labels("En") is LABELS_EN
    assert get_bot_labels("KAA") is LABELS_KAA


def test_get_bot_labels_long_codes_truncate() -> None:
    """``en_US`` should resolve to English, not fall through to Uzbek."""

    assert get_bot_labels("en_US") is LABELS_EN
    assert get_bot_labels("ru-RU") is LABELS_RU


@pytest.mark.parametrize("pack", [LABELS_UZ, LABELS_RU, LABELS_EN, LABELS_KAA])
def test_all_label_fields_non_empty(pack: BotLabels) -> None:
    """Every label field must be a non-empty string."""

    for f in fields(pack):
        value = getattr(pack, f.name)
        assert isinstance(value, str), f"{f.name} is not str"
        assert value, f"{f.name} is empty"


@pytest.mark.parametrize("pack", [LABELS_UZ, LABELS_RU, LABELS_EN, LABELS_KAA])
def test_invoice_template_has_placeholders(pack: BotLabels) -> None:
    """``invoice_created`` carries ``{invoice_number}`` and ``{amount}``."""

    assert "{invoice_number}" in pack.invoice_created
    assert "{amount}" in pack.invoice_created


@pytest.mark.parametrize("pack", [LABELS_UZ, LABELS_RU, LABELS_EN, LABELS_KAA])
def test_balance_template_has_placeholders(pack: BotLabels) -> None:
    assert "{balance}" in pack.balance_info
    assert "{free_today}" in pack.balance_info


@pytest.mark.parametrize("pack", [LABELS_UZ, LABELS_RU, LABELS_EN, LABELS_KAA])
def test_insufficient_balance_template(pack: BotLabels) -> None:
    assert "{balance}" in pack.insufficient_balance
    assert "{required}" in pack.insufficient_balance


@pytest.mark.parametrize("pack", [LABELS_UZ, LABELS_RU, LABELS_EN, LABELS_KAA])
def test_generating_template(pack: BotLabels) -> None:
    assert "{progress}" in pack.generating


@pytest.mark.parametrize("pack", [LABELS_UZ, LABELS_RU, LABELS_EN, LABELS_KAA])
def test_free_credit_template(pack: BotLabels) -> None:
    assert "{amount}" in pack.free_credit_earned


def test_invoice_template_renders_with_format() -> None:
    rendered = LABELS_UZ.invoice_created.format(invoice_number="123456-7890", amount="10,000")
    assert "123456-7890" in rendered
    assert "10,000" in rendered
    assert "{" not in rendered


def test_all_languages_distinct_welcome() -> None:
    """All four welcome strings must be unique — proves no copy/paste bug."""

    welcomes = {LABELS_UZ.welcome, LABELS_RU.welcome, LABELS_EN.welcome, LABELS_KAA.welcome}
    assert len(welcomes) == 4
