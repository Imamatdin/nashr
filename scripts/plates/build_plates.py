"""Print-production for Nashr gate (b): full + coarse-dither plate variants.

Reads raw PNGs from plates/raw/, writes:
  packages/web/public/plates/<asset>.webp          (full, WebP q82)
  packages/web/public/plates/dither/<asset>.webp   (1/5 scale, Bayer 4x4, lossless)
  packages/web/public/plates/manifest.json

Uzbek metadata (alt_uz / title_uz) is taken from PNG text chunks, or from a
sidecar <asset>.json next to the raw PNG. Missing metadata is a hard error --
the manifest must not ship with invented Uzbek strings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

RAW = Path(__file__).resolve().parent.parent / "raw"
OUT = Path(r"C:\Users\imama\Projects\nashr\packages\web\public\plates")

INK = (0x1C, 0x1B, 0x1A)  # Flexoki base-950
CREAM = (0xFF, 0xFC, 0xF0)  # Flexoki paper

BAYER4 = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
]

DITHER_DIVISOR = 5
MAX_DITHER_BYTES = 40 * 1024


def max_width_for(asset: str) -> int:
    if asset == "hero-observatory":
        return 2048
    if asset.startswith("plate-"):
        return 1600
    if asset.startswith("spot-"):
        return 800
    raise SystemExit(f"unknown asset naming (no width rule): {asset}")


def read_metadata(png: Path, img: Image.Image) -> tuple[str, str]:
    sidecar = png.with_suffix(".json")
    info: dict[str, str] = {}
    if sidecar.exists():
        info.update(json.loads(sidecar.read_text(encoding="utf-8")))
    info.update({k: v for k, v in (img.info or {}).items() if isinstance(v, str)})

    def pick(*keys: str) -> str | None:
        for k in keys:
            for have, value in info.items():
                if have.lower() == k and value.strip():
                    return value.strip()
        return None

    alt = pick("alt_uz", "alt", "description")
    title = pick("title_uz", "title")
    if not alt or not title:
        raise SystemExit(
            f"{png.name}: missing Uzbek metadata (need alt_uz + title_uz; "
            f"found keys {sorted(info)})"
        )
    return alt, title


def ordered_dither(gray: Image.Image) -> Image.Image:
    """Bayer 4x4 ordered dither to a two-tone RGB image."""
    w, h = gray.size
    src = gray.load()
    out = Image.new("RGB", (w, h))
    dst = out.load()
    assert src is not None and dst is not None
    for y in range(h):
        row = BAYER4[y & 3]
        for x in range(w):
            threshold = (row[x & 3] + 0.5) * 255.0 / 16.0
            dst[x, y] = CREAM if src[x, y] > threshold else INK
    return out


def build(png: Path) -> dict[str, object]:
    asset = png.stem
    with Image.open(png) as raw:
        raw.load()
        alt, title = read_metadata(png, raw)
        src = raw.convert("RGB")

    target = min(max_width_for(asset), src.width)
    height = max(1, round(src.height * target / src.width))
    full = src.resize((target, height), Image.LANCZOS)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dither").mkdir(parents=True, exist_ok=True)
    full_path = OUT / f"{asset}.webp"
    full.save(full_path, "WEBP", quality=82, method=6)

    dw = max(1, round(full.width / DITHER_DIVISOR))
    dh = max(1, round(full.height / DITHER_DIVISOR))
    small = ImageOps.autocontrast(full.convert("L"), cutoff=1).resize((dw, dh), Image.LANCZOS)
    dither_path = OUT / "dither" / f"{asset}.webp"
    ordered_dither(small).save(dither_path, "WEBP", lossless=True, quality=100, method=6)

    size = dither_path.stat().st_size
    print(
        f"{asset}: full {full.width}x{full.height} "
        f"({full_path.stat().st_size / 1024:.1f} KB) | "
        f"dither {dw}x{dh} ({size / 1024:.1f} KB)"
        + ("  *** OVER 40KB ***" if size > MAX_DITHER_BYTES else "")
    )

    return {
        "full": f"/plates/{asset}.webp",
        "dither": f"/plates/dither/{asset}.webp",
        "width": full.width,
        "height": full.height,
        "alt": alt,
        "title": title,
    }


def main() -> int:
    raws = sorted(RAW.glob("*.png"))
    if not raws:
        print(f"no raw plates in {RAW} -- nothing to build", file=sys.stderr)
        return 1
    manifest = {p.stem: build(p) for p in raws}
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT / 'manifest.json'} ({len(manifest)} assets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
