/*
 * Ported from ThreeUI — "Gallery Heading", the matte (Matte Rise) variant.
 * Source: github.com/MengTo/threeui, src/shaders/neuform-isolated/
 *   sources/gallery-heading.html and NeuformIsolatedEffects.tsx
 *   (GALLERY_HEADING_VARIANTS["rising-diagonal"], field: "matte").
 * Community catalog, MIT License, Copyright (c) 2026 Meng To.
 *
 * Kept verbatim in behaviour: the xorshift rng, the 64x64 value-noise lattice
 * with smoothstep interpolation, fbm, the low-resolution field buffer blown up
 * across the plate, the overlay grain tile, and paintMatte itself — flat colour
 * with one slow rise of noise across it (the move the variant is named for).
 *
 * Replaced: the twelve "grainient" plate colours (violet/chrome/magenta
 * wallpapers built for a black ground) with the Flexoki neutrals this site is
 * drawn in — the plates stand in for deck slides on paper, so they are paper
 * and ink, never decoration. TS (a square 512 texture) becomes a width/height
 * pair, because a slide is 16:9.
 */

const TILE_W = 512;
const TILE_H = 288;

type RGB = [number, number, number];

/** Flexoki plate colours: paper stock with four ink plates for rhythm. */
const PLATES: ReadonlyArray<string> = [
  "#fffcf0",
  "#1c1b1a",
  "#f2f0e5",
  "#fffcf0",
  "#282726",
  "#e6e4d9",
  "#fffcf0",
  "#1c1b1a",
  "#f2f0e5",
  "#fffcf0",
  "#282726",
  "#e6e4d9",
];

export const TILE_COUNT = PLATES.length;
export const TILE_ASPECT = TILE_W / TILE_H;

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s ^= s << 13;
    s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    return s / 4294967296;
  };
}

function canvasOf(w: number, h: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return c;
}

function rgbOf(hex: string): RGB {
  const v = parseInt(hex.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

function mixRGB(a: RGB, b: RGB, t: number): RGB {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

/** Value noise on a 64x64 lattice, smoothstep-interpolated and wrapped. */
function noiseField(seed: number): (x: number, y: number) => number {
  const g = new Float32Array(4096);
  const r = rng(seed);
  for (let i = 0; i < 4096; i++) g[i] = r();
  return (x, y) => {
    const x0 = Math.floor(x);
    const y0 = Math.floor(y);
    let fx = x - x0;
    let fy = y - y0;
    fx = fx * fx * (3 - 2 * fx);
    fy = fy * fy * (3 - 2 * fy);
    const ra = (y0 & 63) * 64;
    const rb = ((y0 + 1) & 63) * 64;
    const ca = x0 & 63;
    const cb = (x0 + 1) & 63;
    const a = g[ra + ca];
    const b = g[ra + cb];
    const c = g[rb + ca];
    const d = g[rb + cb];
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
  };
}

function fbm(n: (x: number, y: number) => number, x: number, y: number, oct: number): number {
  let v = 0;
  let amp = 0.5;
  let f = 1;
  let tot = 0;
  for (let i = 0; i < oct; i++) {
    v += amp * n(x * f, y * f);
    tot += amp;
    amp *= 0.5;
    f *= 2;
  }
  return v / tot;
}

let grainTile: HTMLCanvasElement | null = null;

function grainPattern(): HTMLCanvasElement {
  if (grainTile) return grainTile;
  const c = canvasOf(160, 160);
  const x = c.getContext("2d");
  if (!x) return c;
  const d = x.createImageData(160, 160);
  const r = rng(0x51f3);
  for (let i = 0; i < d.data.length; i += 4) {
    const v = 128 + (r() - 0.5) * 116;
    d.data[i] = v;
    d.data[i + 1] = v;
    d.data[i + 2] = v;
    d.data[i + 3] = 255;
  }
  x.putImageData(d, 0, 0);
  grainTile = c;
  return c;
}

function grain(x: CanvasRenderingContext2D, alpha: number): void {
  const pattern = x.createPattern(grainPattern(), "repeat");
  if (!pattern) return;
  x.save();
  x.globalCompositeOperation = "overlay";
  x.globalAlpha = alpha;
  x.fillStyle = pattern;
  x.fillRect(0, 0, TILE_W, TILE_H);
  x.restore();
}

/** Paint a low-resolution field, then blow it up over the whole plate. */
function fieldBuffer(n: number, shade: (u: number, v: number) => RGB): HTMLCanvasElement {
  const buf = canvasOf(n, n);
  const bx = buf.getContext("2d");
  if (!bx) return buf;
  const d = bx.createImageData(n, n);
  for (let py = 0; py < n; py++) {
    for (let px = 0; px < n; px++) {
      const c = shade((px + 0.5) / n, (py + 0.5) / n);
      const o = (py * n + px) * 4;
      d.data[o] = c[0] | 0;
      d.data[o + 1] = c[1] | 0;
      d.data[o + 2] = c[2] | 0;
      d.data[o + 3] = 255;
    }
  }
  bx.putImageData(d, 0, 0);
  return buf;
}

/**
 * matte — a museum plate: flat colour, one slow rise of noise across it.
 *
 * The source tunes its field for a 512px square seen large on black; the same
 * amplitude on a 16:9 plate a few hundred pixels wide reads as camouflage. The
 * rise is kept, its swing is not: the noise term is damped and the vertical
 * gradient carries most of the shading, so the plate reads as stock.
 */
function paintMatte(x: CanvasRenderingContext2D, base: RGB, index: number): void {
  const n = noiseField(0x2c41 + index * 9176);
  const hi = mixRGB(base, [255, 255, 255], 0.1);
  const lo = mixRGB(base, [0, 0, 0], 0.1);
  const buf = fieldBuffer(160, (u, v) => {
    let s = 0.5 + (fbm(n, u * 3.1, v * 3.1, 5) - 0.5) * 0.5 + (0.5 - v) * 0.34;
    s = s < 0 ? 0 : s > 1 ? 1 : s;
    return s < 0.5 ? mixRGB(lo, base, s * 2) : mixRGB(base, hi, (s - 0.5) * 2);
  });
  x.save();
  x.imageSmoothingEnabled = true;
  x.drawImage(buf, 0, 0, TILE_W, TILE_H);
  x.restore();
  grain(x, 0.06);
}

/**
 * Ours, not the source's: the placeholder has to read as a SLIDE at ring scale,
 * so each plate carries the skeleton of one — a rule, a title band, two lines
 * of body, drawn in the plate's own ink at low weight. No lettering: a fake
 * sentence at this size is noise, and these plates are replaced by real deck
 * renders the moment the founder supplies them.
 */
function slideSkeleton(x: CanvasRenderingContext2D, base: RGB, index: number): void {
  const dark = base[0] + base[1] + base[2] < 300;
  const ink = dark ? "#fffcf0" : "#1c1b1a";
  const pad = 52;
  const bar = 26;

  x.save();
  x.fillStyle = ink;

  // The gilded rule: one per plate, the same mark the site uses for eyebrows.
  x.globalAlpha = 1;
  x.fillStyle = "#ad8301";
  x.fillRect(pad, pad, 64, 5);

  x.fillStyle = ink;
  x.globalAlpha = dark ? 0.92 : 0.86;
  const title = index % 3 === 0 ? 250 : index % 3 === 1 ? 330 : 200;
  x.fillRect(pad, pad + 34, title, bar);

  x.globalAlpha = dark ? 0.34 : 0.26;
  x.fillRect(pad, pad + 34 + bar + 22, 300, 8);
  x.fillRect(pad, pad + 34 + bar + 44, 232, 8);

  // A figure block on every third plate: a deck is not all text.
  if (index % 3 === 2) {
    x.globalAlpha = dark ? 0.22 : 0.16;
    for (let i = 0; i < 4; i++) {
      const h = 26 + ((index * 13 + i * 29) % 62);
      x.fillRect(TILE_W - pad - 150 + i * 38, TILE_H - pad - h, 24, h);
    }
  }

  x.restore();
}

export interface TileTextures {
  front: HTMLCanvasElement[];
  back: HTMLCanvasElement[];
  width: number;
  height: number;
}

/** The far half of the ring keeps its colour but loses its light. */
function reverseOf(front: HTMLCanvasElement): HTMLCanvasElement {
  const d = canvasOf(TILE_W, TILE_H);
  const y = d.getContext("2d");
  if (!y) return d;
  y.drawImage(front, 0, 0);
  y.globalCompositeOperation = "saturation";
  y.fillStyle = "rgba(128,128,128,0.2)";
  y.fillRect(0, 0, TILE_W, TILE_H);
  y.globalCompositeOperation = "multiply";
  // Neutral rather than the source's blue-black: this ring hangs on paper.
  y.fillStyle = "rgba(28,27,26,0.30)";
  y.fillRect(0, 0, TILE_W, TILE_H);
  return d;
}

/** A plate drawn from a supplied slide image, cover-fitted into the tile. */
function plateFromImage(image: HTMLImageElement): HTMLCanvasElement {
  const c = canvasOf(TILE_W, TILE_H);
  const x = c.getContext("2d");
  if (!x) return c;
  const scale = Math.max(TILE_W / image.naturalWidth, TILE_H / image.naturalHeight);
  const w = image.naturalWidth * scale;
  const h = image.naturalHeight * scale;
  x.fillStyle = "#fffcf0";
  x.fillRect(0, 0, TILE_W, TILE_H);
  x.drawImage(image, (TILE_W - w) / 2, (TILE_H - h) / 2, w, h);
  return c;
}

function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = src;
  });
}

/**
 * The twelve plates. Supplied slide images win; every slot without one falls
 * back to the ported matte painter, so the ring is complete from the first
 * render and never shows a hole while the founder assets are outstanding.
 */
export async function buildTiles(sources: ReadonlyArray<string>): Promise<TileTextures> {
  const images = await Promise.all(
    Array.from({ length: TILE_COUNT }, (_, i) => (sources[i] ? loadImage(sources[i]) : null)),
  );

  const front: HTMLCanvasElement[] = [];
  const back: HTMLCanvasElement[] = [];
  for (let i = 0; i < TILE_COUNT; i++) {
    const image = images[i];
    let plate: HTMLCanvasElement;
    if (image) {
      plate = plateFromImage(image);
    } else {
      plate = canvasOf(TILE_W, TILE_H);
      const x = plate.getContext("2d");
      if (x) {
        paintMatte(x, rgbOf(PLATES[i]), i);
        slideSkeleton(x, rgbOf(PLATES[i]), i);
      }
    }
    front.push(plate);
    back.push(reverseOf(plate));
  }
  return { front, back, width: TILE_W, height: TILE_H };
}
