"""The one article exporter: profiles as data, a single builder, a compliance
checker, a DOCX-to-PDF step through the shared office runner, and a bot adapter.

This package replaces the three previous article exporters (D7). Callers build an
:class:`ArticleExportInput` and run it through :class:`ArticleExporter`; the bot's
drafted-article path reaches the same builder through ``adapter.py``.
"""

from __future__ import annotations

from packages.workers.article.export.builder import ArticleExporter
from packages.workers.article.export.checker import (
    ComplianceCheck,
    ComplianceReport,
    check_compliance,
)
from packages.workers.article.export.models import (
    ArticleAuthorship,
    ArticleExportInput,
    BuiltArticle,
    ComplianceStatus,
    UnresolvedCitationError,
)
from packages.workers.article.export.profiles import (
    ArticleProfile,
    ArticleProfileId,
    all_profiles,
    get_profile,
    profile_ids,
)

__all__ = [
    "ArticleAuthorship",
    "ArticleExportInput",
    "ArticleExporter",
    "ArticleProfile",
    "ArticleProfileId",
    "BuiltArticle",
    "ComplianceCheck",
    "ComplianceReport",
    "ComplianceStatus",
    "UnresolvedCitationError",
    "all_profiles",
    "check_compliance",
    "get_profile",
    "profile_ids",
]
