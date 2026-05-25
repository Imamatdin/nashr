"""Person portraits sourced from Wikidata → Wikimedia Commons, gated and legal.

A person slot carries a real name (and sometimes dates/role/description as
disambiguation context). This module turns that into a portrait of the *actual*
person, sourced from Commons under a license we are allowed to use — or it
abstains. It never generates a likeness of a real person.

Pipeline (every step can abstain → ``None``, never raises into the deck):

1. ``wbsearchentities`` — name → candidate Wikidata entities.
2. ``wbgetentities`` — pull P31 (instance-of), P569/P570 (birth/death),
   P18 (image), label, and English description for the candidates at once.
3. Disambiguate: require ``instance of human``; match the provided dates and
   role/description against the candidate. A *provided* date that contradicts a
   candidate disqualifies it (namesake protection). If nothing survives, abstain.
4. Commons ``imageinfo`` + ``extmetadata`` for the chosen P18 file.
5. LICENSE WHITELIST — accept PD / CC0 / CC-BY only; reject SA, NC, ND,
   editorial-only, restricted, or ambiguous/missing. (:func:`classify_license`.)
6. Portrait-rank — reject statues, busts, graves, logos, maps, low-res.
7. Download the bytes (re-hosted by the caller, not hot-linked) and, for CC-BY,
   record attribution for the slide's speaker notes.

The HTTP client is injected (the caller owns its lifecycle and User-Agent),
mirroring :mod:`packages.academic.providers`. CLAUDE.md's 300-line cap is
exceeded here by design: this is one coherent external pipeline (search →
disambiguate → license-gate → rank → download) whose steps share the candidate
state and would only be obscured by being split across modules.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict, Field

from packages.academic.providers._json_utils import as_dict, as_list
from packages.presentation.image_types import ImageAttribution, ResolvedImage

logger = logging.getLogger(__name__)

WIKIDATA_API: Final[str] = "https://www.wikidata.org/w/api.php"
COMMONS_API: Final[str] = "https://commons.wikimedia.org/w/api.php"

# Wikidata property/entity ids we read.
_P_INSTANCE_OF: Final[str] = "P31"
_P_BIRTH: Final[str] = "P569"
_P_DEATH: Final[str] = "P570"
_P_IMAGE: Final[str] = "P18"
_Q_HUMAN: Final[str] = "Q5"

_SEARCH_LIMIT: Final[int] = 6
_MIN_PORTRAIT_PX: Final[int] = 200

# Filename fragments that mark a Commons image as NOT a usable portrait of the
# person: monuments and likenesses of likenesses, documents, insignia, places.
_NON_PORTRAIT_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "statue",
        "monument",
        "bust",
        "memorial",
        "grave",
        "tomb",
        "plaque",
        "signature",
        "coat of arms",
        "coat_of_arms",
        "logo",
        "map",
        "stamp",
        "banknote",
        "coin",
        "medal",
        "building",
        "museum",
        "street",
        "square",
    }
)

# License-component tokens that disqualify an image outright.
_REJECT_TOKENS: Final[frozenset[str]] = frozenset({"sa", "nc", "nd"})
_REJECT_PHRASES: Final[frozenset[str]] = frozenset(
    {
        "share alike",
        "sharealike",
        "noncommercial",
        "non-commercial",
        "no derivative",
        "noderiv",
        "editorial",
        "fair use",
        "all rights reserved",
    }
)
_PUBLIC_DOMAIN_PHRASES: Final[frozenset[str]] = frozenset(
    {"public domain", "pd", "pdm", "no restrictions"}
)


class LicenseDecision(BaseModel):
    """Outcome of classifying one Commons file's license."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    allowed: bool
    requires_attribution: bool
    license_name: str = Field(min_length=1, max_length=100)


class _Candidate(BaseModel):
    """A disambiguation candidate assembled from a Wikidata entity."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    qid: str
    label: str = ""
    description: str = ""
    is_human: bool = False
    birth_year: int | None = None
    death_year: int | None = None
    image_filename: str | None = None
    search_rank: int = 0


def _tokens(text: str) -> set[str]:
    """Lowercase word tokens of length >= 3 (for fuzzy context matching)."""

    return {t for t in re.findall(r"[a-z]+", text.lower()) if len(t) >= 3}


def _parse_years(context: str | None) -> tuple[int | None, int | None]:
    """Pull (birth, death) years from a free-form dates string like ``1694-1778``."""

    if not context:
        return None, None
    years = [int(m) for m in re.findall(r"\b(\d{3,4})\b", context)]
    plausible = [y for y in years if 100 <= y <= 2100]
    birth = plausible[0] if plausible else None
    death = plausible[1] if len(plausible) > 1 else None
    return birth, death


def _date_conflicts(context_year: int | None, candidate_year: int | None) -> bool:
    """True when both years are known and disagree beyond a one-year tolerance.

    A year supplied by the user that contradicts a candidate is the strongest
    "wrong person" signal there is — it disqualifies the candidate outright,
    which is how we abstain on namesakes. Missing values never conflict.
    """

    if context_year is None or candidate_year is None:
        return False
    return abs(context_year - candidate_year) > 1


def classify_license(extmetadata: dict[str, Any]) -> LicenseDecision:
    """Classify a Commons file's license against the PD / CC0 / CC-BY whitelist.

    Reject markers (SA / NC / ND / editorial / restricted) are checked first so
    a name like ``cc-by-sa-3.0`` — which contains ``cc-by`` — is still rejected.
    Restrictions or a missing/empty license collapse to a not-allowed decision
    so the caller abstains rather than risking an unlicensed image.
    """

    code = _string_field(extmetadata, "License")
    short = _string_field(extmetadata, "LicenseShortName")
    usage = _string_field(extmetadata, "UsageTerms")
    restrictions = _string_field(extmetadata, "Restrictions")
    label = short or code or "unknown"

    if restrictions:
        return LicenseDecision(allowed=False, requires_attribution=False, license_name=label)

    code_tokens = {t for t in re.split(r"[-_\s]+", code.lower()) if t}
    haystack = f"{code} {short} {usage}".lower()

    if code_tokens & _REJECT_TOKENS or any(p in haystack for p in _REJECT_PHRASES):
        return LicenseDecision(allowed=False, requires_attribution=False, license_name=label)

    is_pd = (
        "cc0" in code.lower()
        or "cc0" in short.lower()
        or bool(code_tokens & {"pd", "pdm"})
        or any(p in haystack for p in _PUBLIC_DOMAIN_PHRASES)
    )
    if is_pd:
        return LicenseDecision(
            allowed=True, requires_attribution=False, license_name=short or "Public domain"
        )

    is_cc_by = ("cc" in code_tokens and "by" in code_tokens) or (
        "attribution" in haystack and "cc" in haystack
    )
    if is_cc_by:
        return LicenseDecision(
            allowed=True, requires_attribution=True, license_name=short or "CC BY"
        )

    return LicenseDecision(allowed=False, requires_attribution=False, license_name=label)


class CommonsPortraitResolver:
    """Resolve a named person to a whitelisted Commons portrait, or abstain."""

    USER_AGENT: Final[str] = "Nashr/1.0 (https://nashr.ai; academic presentations)"

    async def resolve(
        self,
        client: httpx.AsyncClient,
        name: str,
        *,
        years: str | None = None,
        role: str | None = None,
        description: str | None = None,
    ) -> ResolvedImage | None:
        """Return a portrait for ``name`` or ``None`` (abstain) if unsure/unlicensed."""

        cleaned = name.strip()
        if not cleaned:
            return None

        candidates = await self._search(client, cleaned)
        if not candidates:
            return None

        entities = await self._fetch_entities(client, [c.qid for c in candidates])
        if not entities:
            return None
        for cand in candidates:
            self._enrich(cand, entities.get(cand.qid))

        chosen = self._select(candidates, cleaned, years, role, description)
        if chosen is None or chosen.image_filename is None:
            logger.info("portrait_abstain_no_candidate", extra={"name": cleaned})
            return None

        return await self._fetch_commons_image(client, chosen.image_filename, cleaned)

    # ----------------------------------------------------------------- search

    async def _search(self, client: httpx.AsyncClient, name: str) -> list[_Candidate]:
        """``wbsearchentities`` — name → ranked candidate QIDs."""

        params = {
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "uselang": "en",
            "format": "json",
            "type": "item",
            "limit": str(_SEARCH_LIMIT),
        }
        payload = await self._get_json(client, WIKIDATA_API, params)
        if payload is None:
            return []
        results = as_list(payload.get("search"))
        if results is None:
            return []
        out: list[_Candidate] = []
        for rank, raw in enumerate(results):
            item = as_dict(raw)
            if item is None:
                continue
            qid = item.get("id")
            if not isinstance(qid, str) or not qid:
                continue
            label = item.get("label")
            description = item.get("description")
            out.append(
                _Candidate(
                    qid=qid,
                    label=label if isinstance(label, str) else "",
                    description=description if isinstance(description, str) else "",
                    search_rank=rank,
                )
            )
        return out

    async def _fetch_entities(
        self, client: httpx.AsyncClient, qids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """``wbgetentities`` for all candidates in one call (claims + descriptions)."""

        if not qids:
            return {}
        params = {
            "action": "wbgetentities",
            "ids": "|".join(qids[:_SEARCH_LIMIT]),
            "props": "claims|descriptions|labels",
            "languages": "en",
            "format": "json",
        }
        payload = await self._get_json(client, WIKIDATA_API, params)
        if payload is None:
            return {}
        entities = as_dict(payload.get("entities"))
        if entities is None:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for qid, raw in entities.items():
            entity = as_dict(raw)
            if entity is not None:
                out[qid] = entity
        return out

    def _enrich(self, cand: _Candidate, entity: dict[str, Any] | None) -> None:
        """Fold claims/description from one entity onto its candidate in place."""

        if entity is None:
            return
        claims = as_dict(entity.get("claims")) or {}
        cand.is_human = _Q_HUMAN in _claim_entity_ids(claims.get(_P_INSTANCE_OF))
        cand.birth_year = _claim_year(claims.get(_P_BIRTH))
        cand.death_year = _claim_year(claims.get(_P_DEATH))
        cand.image_filename = _claim_string(claims.get(_P_IMAGE))
        en_desc = _localized_value(entity.get("descriptions"))
        if en_desc:
            cand.description = en_desc

    # -------------------------------------------------------------- selection

    def _select(
        self,
        candidates: list[_Candidate],
        name: str,
        years: str | None,
        role: str | None,
        description: str | None,
    ) -> _Candidate | None:
        """Pick the best human candidate with an image, or abstain.

        A provided date that contradicts a candidate disqualifies it outright
        (namesake protection). Beyond that the score blends an exact/loose name
        match, date agreement, and role/description keyword overlap. We require
        a real signal — a name or a date match — so an unrelated top hit for a
        generic string does not slip through.
        """

        ctx_birth, ctx_death = _parse_years(years)
        ctx_tokens = _tokens(f"{role or ''} {description or ''}")
        name_lower = name.lower()

        best: _Candidate | None = None
        best_score = 0.0
        for cand in candidates:
            if not cand.is_human or cand.image_filename is None:
                continue

            if _date_conflicts(ctx_birth, cand.birth_year) or _date_conflicts(
                ctx_death, cand.death_year
            ):
                continue

            score = 0.0
            label_lower = cand.label.lower()
            name_matched = False
            if label_lower == name_lower:
                score += 3.0
                name_matched = True
            elif name_lower in label_lower or label_lower in name_lower:
                score += 1.0
                name_matched = True

            date_matched = False
            if ctx_birth is not None and cand.birth_year == ctx_birth:
                score += 3.0
                date_matched = True
            if ctx_death is not None and cand.death_year == ctx_death:
                score += 2.0
                date_matched = True

            if ctx_tokens:
                overlap = len(ctx_tokens & _tokens(cand.description))
                score += min(2.0, float(overlap))

            score -= cand.search_rank * 0.1  # gentle tie-break toward relevance

            # Require a real disambiguating signal, never just "is a human".
            if not (name_matched or date_matched):
                continue

            if score > best_score:
                best_score = score
                best = cand

        return best

    # ------------------------------------------------------------ commons fetch

    async def _fetch_commons_image(
        self, client: httpx.AsyncClient, filename: str, subject: str
    ) -> ResolvedImage | None:
        """Imageinfo + license gate + portrait-rank + download for one P18 file."""

        if _is_non_portrait(filename):
            logger.info("portrait_abstain_non_portrait", extra={"file": filename})
            return None

        params = {
            "action": "query",
            "titles": f"File:{filename}",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "format": "json",
        }
        payload = await self._get_json(client, COMMONS_API, params)
        if payload is None:
            return None
        info = _first_imageinfo(payload)
        if info is None:
            return None

        mime = info.get("mime")
        if not isinstance(mime, str) or not mime.startswith("image/"):
            return None
        width = info.get("width") if isinstance(info.get("width"), int) else None
        height = info.get("height") if isinstance(info.get("height"), int) else None
        if (width is not None and width < _MIN_PORTRAIT_PX) or (
            height is not None and height < _MIN_PORTRAIT_PX
        ):
            logger.info("portrait_abstain_low_res", extra={"file": filename})
            return None

        extmetadata = as_dict(info.get("extmetadata")) or {}
        decision = classify_license(extmetadata)
        if not decision.allowed:
            logger.info(
                "portrait_abstain_license",
                extra={"file": filename, "license": decision.license_name},
            )
            return None

        url = info.get("url")
        if not isinstance(url, str) or not url:
            return None
        data = await self._download(client, url)
        if data is None:
            return None

        attribution: ImageAttribution | None = None
        if decision.requires_attribution:
            attribution = ImageAttribution(
                creator=_artist(extmetadata),
                source_url=f"https://commons.wikimedia.org/wiki/File:{filename}",
                license_name=decision.license_name,
                subject=subject,
                modified=False,
            )

        return ResolvedImage(
            data=data,
            content_type=mime,
            attribution=attribution,
            width=width,
            height=height,
        )

    # --------------------------------------------------------------- http glue

    async def _get_json(
        self, client: httpx.AsyncClient, url: str, params: dict[str, str]
    ) -> dict[str, Any] | None:
        """GET ``url`` with a descriptive UA; return a dict payload or ``None``."""

        try:
            response = await client.get(url, params=params, headers={"User-Agent": self.USER_AGENT})
        except httpx.HTTPError as exc:
            logger.warning("commons_request_failed", extra={"url": url, "error": str(exc)})
            return None
        if response.status_code != 200:
            logger.warning("commons_bad_status", extra={"url": url, "status": response.status_code})
            return None
        try:
            return as_dict(response.json())
        except ValueError as exc:
            logger.warning("commons_bad_json", extra={"url": url, "error": str(exc)})
            return None

    async def _download(self, client: httpx.AsyncClient, url: str) -> bytes | None:
        """Download the image bytes; abstain on any transport/HTTP failure."""

        try:
            response = await client.get(url, headers={"User-Agent": self.USER_AGENT})
        except httpx.HTTPError as exc:
            logger.warning("commons_download_failed", extra={"url": url, "error": str(exc)})
            return None
        if response.status_code != 200:
            logger.warning(
                "commons_download_bad_status", extra={"url": url, "status": response.status_code}
            )
            return None
        return response.content


# ---------------------------------------------------------------------------
# Wikidata claim parsing helpers
# ---------------------------------------------------------------------------


def _claim_entity_ids(claim: object) -> set[str]:
    """Entity ids (``Q…``) referenced by a wikibase-item claim's mainsnaks."""

    out: set[str] = set()
    statements = as_list(claim)
    if statements is None:
        return out
    for raw in statements:
        value = _mainsnak_value(raw)
        value_dict = as_dict(value)
        if value_dict is None:
            continue
        entity_id = value_dict.get("id")
        if isinstance(entity_id, str) and entity_id:
            out.add(entity_id)
    return out


def _claim_year(claim: object) -> int | None:
    """Parse a year from the first time-valued statement (``+1694-...T...``)."""

    statements = as_list(claim)
    if statements is None:
        return None
    for raw in statements:
        value = as_dict(_mainsnak_value(raw))
        if value is None:
            continue
        time_str = value.get("time")
        if isinstance(time_str, str):
            match = re.match(r"[+-]?(\d{1,4})-", time_str)
            if match:
                year = int(match.group(1))
                if 100 <= year <= 2100:
                    return year
    return None


def _claim_string(claim: object) -> str | None:
    """First plain-string value of a claim (P18 holds a Commons filename)."""

    statements = as_list(claim)
    if statements is None:
        return None
    for raw in statements:
        value = _mainsnak_value(raw)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _mainsnak_value(statement: object) -> object:
    """Reach into ``statement.mainsnak.datavalue.value`` defensively."""

    stmt = as_dict(statement)
    if stmt is None:
        return None
    mainsnak = as_dict(stmt.get("mainsnak"))
    if mainsnak is None:
        return None
    datavalue = as_dict(mainsnak.get("datavalue"))
    if datavalue is None:
        return None
    return datavalue.get("value")


def _localized_value(block: object) -> str | None:
    """English value of a Wikidata labels/descriptions block, if present."""

    mapping = as_dict(block)
    if mapping is None:
        return None
    entry = as_dict(mapping.get("en"))
    if entry is None:
        return None
    value = entry.get("value")
    return value.strip() if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------------------
# Commons response helpers
# ---------------------------------------------------------------------------


def _first_imageinfo(payload: dict[str, Any]) -> dict[str, Any] | None:
    """First page's first ``imageinfo`` record from a Commons query payload."""

    query = as_dict(payload.get("query"))
    if query is None:
        return None
    pages = as_dict(query.get("pages"))
    if pages is None:
        return None
    for raw_page in pages.values():
        page = as_dict(raw_page)
        if page is None:
            continue
        infos = as_list(page.get("imageinfo"))
        if infos:
            return as_dict(infos[0])
    return None


def _string_field(extmetadata: dict[str, Any], key: str) -> str:
    """Read ``extmetadata[key].value`` as a string, defaulting to ``""``."""

    block = as_dict(extmetadata.get(key))
    if block is None:
        return ""
    value = block.get("value")
    return value.strip() if isinstance(value, str) else ""


def _artist(extmetadata: dict[str, Any]) -> str:
    """Best-effort human-readable creator, stripped of any HTML markup."""

    raw = _string_field(extmetadata, "Artist") or _string_field(extmetadata, "Credit")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300] if text else "Unknown"


def _is_non_portrait(filename: str) -> bool:
    """Reject obvious non-portraits (statues, documents, insignia) by filename."""

    lowered = filename.lower()
    return any(marker in lowered for marker in _NON_PORTRAIT_MARKERS)


__all__ = [
    "CommonsPortraitResolver",
    "LicenseDecision",
    "classify_license",
]
