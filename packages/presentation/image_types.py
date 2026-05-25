"""Value types shared across the image engine.

The image engine resolves three kinds of slot — person portraits sourced from
Wikimedia Commons (:mod:`packages.presentation.commons_portraits`), and
object/concept/scene images produced by source-informed generation
(:mod:`packages.presentation.image_generation`). Both paths converge on a
single :class:`ResolvedImage` that :class:`packages.presentation.image_pass.ImagePass`
uploads and references, so the stage never branches on where an image came from.

These are internal value objects, not part of the deck wire format: the only
thing that reaches the rendered deck is a ``_url`` string (and, for CC-BY
sources, an attribution line folded into the slide's ``speaker_notes`` — there
is no separate credits slide).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Content-type → file extension for the few raster formats Commons portraits and
# the generator actually emit. Unknown ``image/*`` types fall back to the mime
# subtype; anything non-image falls back to ``.png``.
_EXT_BY_CONTENT_TYPE: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/tiff": ".tiff",
}


def extension_for_content_type(content_type: str) -> str:
    """Map a content type to a file extension, defaulting sensibly.

    A known raster type maps directly; an unrecognised ``image/<sub>`` becomes
    ``.<sub>`` (dropping any ``+suffix``); anything else falls back to ``.png``
    so an upload always has a usable extension.
    """

    normalized = content_type.split(";", 1)[0].strip().lower()
    mapped = _EXT_BY_CONTENT_TYPE.get(normalized)
    if mapped is not None:
        return mapped
    if normalized.startswith("image/"):
        subtype = normalized.removeprefix("image/").split("+", 1)[0]
        if subtype:
            return f".{subtype}"
    return ".png"


class ImageAttribution(BaseModel):
    """Credit for a sourced image whose license requires attribution (CC-BY).

    PD and CC0 images carry no attribution and never produce one of these.
    The ImagePass folds :meth:`to_note` into the affected slide's
    ``speaker_notes`` — off the visible slide, but present in the deck — which
    satisfies CC-BY's attribution condition without a dedicated credits slide.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    creator: str = Field(min_length=1, max_length=300)
    source_url: str = Field(min_length=1, max_length=1000)
    license_name: str = Field(min_length=1, max_length=100)
    subject: str | None = Field(default=None, max_length=300)
    modified: bool = False

    def to_note(self) -> str:
        """Render a single attribution line for ``speaker_notes``."""

        who = f"{self.subject}: " if self.subject else ""
        changed = ", modified" if self.modified else ""
        return (
            f"Image — {who}{self.creator}, {self.license_name}{changed} "
            f"(via Wikimedia Commons: {self.source_url})"
        )


class ResolvedImage(BaseModel):
    """One resolved image, ready for the ImagePass to upload and reference.

    Both the Commons resolver and the generator return this. ``data`` is the
    raw image bytes (re-hosted via :class:`packages.platform.storage.FileStorage`
    rather than hot-linked); ``attribution`` is set only for CC-BY sources.
    """

    model_config = ConfigDict(extra="forbid")

    data: bytes
    content_type: str = Field(min_length=1, max_length=100)
    attribution: ImageAttribution | None = None
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)

    @property
    def extension(self) -> str:
        """File extension implied by :attr:`content_type`."""

        return extension_for_content_type(self.content_type)


__all__ = [
    "ImageAttribution",
    "ResolvedImage",
    "extension_for_content_type",
]
