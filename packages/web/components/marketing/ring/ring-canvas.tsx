"use client";

/*
 * Ported from ThreeUI — "Gallery Heading", the matte (Matte Rise) variant.
 * Source: github.com/MengTo/threeui, src/shaders/neuform-isolated/
 *   sources/gallery-heading.html. Community catalog, MIT License,
 *   Copyright (c) 2026 Meng To.
 *
 * Kept: the ring configuration (twelve plates, a 0.492 projected ratio — a
 * 60.5deg plane tilt — a 25.5deg major axis, 93deg starting phase, a camera
 * thirteen ring radii back), the U/V basis and the U x V ring axis, the
 * perspective divide in project(), the per-plate parallelogram transform with
 * its rounded-rect clip, the painter's-algorithm z-sort, the edge-on cull, and
 * the device-pixel-ratio-capped resize.
 *
 * Replaced: the black ground with none at all — the paper shows through, since
 * this ring hangs on a light page. The baked headline and label layers are
 * dropped: our headline is DOM text beside the ring, not pixels inside it. The
 * hover-gated spring rate becomes a constant slow orbit with the spring moved
 * onto pointer parallax (the brief asks for orbit plus parallax, nothing
 * scroll-bound). Square plates become 16:9, because they stand in for slides.
 *
 * Added: the render loop stops — rAF cancelled, not merely hidden — whenever
 * the ring leaves the viewport or the tab is backgrounded.
 */

import { useEffect, useRef } from "react";
import { buildTiles, TILE_ASPECT, TILE_COUNT, type TileTextures } from "./ring-art";

/** Seconds per revolution. The source loops in 15s; a hero wants calmer. */
const SPIN_SECONDS = 44;

const RING = {
  ratio: 0.492,
  axis: 25.5,
  radius: 0.22,
  dist: 13,
  phase: 93,
  /** Plate half-width as a fraction of the ring radius. */
  half: 0.245,
};

const SPRING_K = 26;
const SPRING_D = 5.7;
const YAW = 0.11;
const PITCH = 0.07;

type Vec3 = [number, number, number];

const ax = (RING.axis * Math.PI) / 180;
const cf = RING.ratio;
const sf = Math.sqrt(1 - cf * cf);
const U: Vec3 = [Math.cos(ax), Math.sin(ax), 0];
const V: Vec3 = [-Math.sin(ax) * cf, Math.cos(ax) * cf, sf];
const AXIS: Vec3 = [
  U[1] * V[2] - U[2] * V[1],
  U[2] * V[0] - U[0] * V[2],
  U[0] * V[1] - U[1] * V[0],
];

function tilt(v: Vec3, yaw: number, pitch: number): Vec3 {
  const cy = Math.cos(yaw);
  const sy = Math.sin(yaw);
  const x = v[0] * cy + v[2] * sy;
  let z = -v[0] * sy + v[2] * cy;
  const cp = Math.cos(pitch);
  const sp = Math.sin(pitch);
  const y = v[1] * cp - z * sp;
  z = v[1] * sp + z * cp;
  return [x, y, z];
}

function roundRectPath(x: CanvasRenderingContext2D, w: number, h: number, r: number): void {
  x.beginPath();
  x.moveTo(-w / 2 + r, -h / 2);
  x.lineTo(w / 2 - r, -h / 2);
  x.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
  x.lineTo(w / 2, h / 2 - r);
  x.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
  x.lineTo(-w / 2 + r, h / 2);
  x.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
  x.lineTo(-w / 2, -h / 2 + r);
  x.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
  x.closePath();
}

export interface RingCanvasProps {
  tiles: ReadonlyArray<string>;
  onReady?: () => void;
}

/**
 * The whole runtime, taking its canvas as an argument rather than reading a ref
 * inside every closure. Returns its own teardown.
 */
function mount(
  canvas: HTMLCanvasElement,
  ctx: CanvasRenderingContext2D,
  tiles: ReadonlyArray<string>,
  onReady: () => void,
): () => void {
  let textures: TileTextures | null = null;
  let frameId = 0;
  let running = false;
  let visible = true;
  let disposed = false;

  let width = 0;
  let height = 0;
  let radius = 0;
  let originX = 0;
  let originY = 0;

  // Pointer parallax, sprung: the ring leans toward the cursor and rocks once
  // as it settles, then holds. Pointer coordinates are -1..1 off the centre.
  let targetX = 0;
  let targetY = 0;
  let leanX = 0;
  let leanY = 0;
  let velX = 0;
  let velY = 0;

  let clock = 0;
  let last = 0;

  function resize(): void {
    const box = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = Math.round(box.width * dpr);
    height = Math.round(box.height * dpr);
    if (width === 0 || height === 0) return;
    canvas.width = width;
    canvas.height = height;
    originX = width / 2;
    originY = height / 2;
    // The projected ellipse, rotated onto the major axis, plus one plate and
    // the nearest plate's perspective gain. Solved rather than eyeballed so
    // the composition never clips at an odd viewport.
    // At the horizontal extremes of the ellipse a plate stands nearly edge-on,
    // so it is its HEIGHT that reaches sideways, not its width — and the other
    // way round top and bottom. Adding the full width at both would leave the
    // ring floating in a third of the box.
    const near = RING.dist / (RING.dist - sf);
    const halfH = RING.half / TILE_ASPECT;
    const spanX = Math.hypot(Math.cos(ax), cf * Math.sin(ax)) + halfH * 0.9 + RING.half * 0.25;
    const spanY = Math.hypot(Math.sin(ax), cf * Math.cos(ax)) + RING.half * 0.45 + halfH * 0.5;
    radius = Math.min(width / (2 * spanX * near), height / (2 * spanY * near)) * 0.99;
  }

  function project(p: Vec3): [number, number] {
    const k = (radius * RING.dist) / (RING.dist - p[2]);
    return [originX + k * p[0], originY + k * p[1]];
  }

  function drawPlate(index: number, psi: number, u: Vec3, v: Vec3, axis: Vec3): void {
    if (!textures) return;
    const c = Math.cos(psi);
    const s = Math.sin(psi);
    const centre: Vec3 = [
      c * u[0] + s * v[0],
      c * u[1] + s * v[1],
      c * u[2] + s * v[2],
    ];
    const tangent: Vec3 = [
      -s * u[0] + c * v[0],
      -s * u[1] + c * v[1],
      -s * u[2] + c * v[2],
    ];
    const halfH = RING.half / TILE_ASPECT;
    const p0 = project(centre);
    const pT = project([
      centre[0] + tangent[0] * RING.half,
      centre[1] + tangent[1] * RING.half,
      centre[2] + tangent[2] * RING.half,
    ]);
    // U x V points down the screen for this basis, so the plate is sampled
    // against the axis: without the sign the artwork renders upside down.
    const pA = project([
      centre[0] - axis[0] * halfH,
      centre[1] - axis[1] * halfH,
      centre[2] - axis[2] * halfH,
    ]);
    const ex = pT[0] - p0[0];
    const ey = pT[1] - p0[1];
    const fx = pA[0] - p0[0];
    const fy = pA[1] - p0[1];
    if (Math.abs(ex * fy - ey * fx) < 0.4) return;

    const face = centre[2] > 0 ? textures.front : textures.back;
    const image = face[index % face.length];
    const { width: tw, height: th } = textures;
    ctx.save();
    ctx.setTransform((ex * 2) / tw, (ey * 2) / tw, (fx * 2) / th, (fy * 2) / th, p0[0], p0[1]);
    roundRectPath(ctx, tw, th, th * RING.radius);
    ctx.clip();
    ctx.drawImage(image, -tw / 2, -th / 2, tw, th);
    ctx.restore();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  function render(): void {
    if (!textures || width === 0) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.imageSmoothingQuality = "high";

    const u = tilt(U, leanX * YAW, leanY * PITCH);
    const v = tilt(V, leanX * YAW, leanY * PITCH);
    const axis = tilt(AXIS, leanX * YAW, leanY * PITCH);

    const spin = (clock / SPIN_SECONDS) * Math.PI * 2;
    const order: Array<{ index: number; psi: number; z: number }> = [];
    for (let i = 0; i < TILE_COUNT; i++) {
      const psi = (RING.phase * Math.PI) / 180 - (i * 2 * Math.PI) / TILE_COUNT + spin;
      order.push({ index: i, psi, z: Math.cos(psi) * u[2] + Math.sin(psi) * v[2] });
    }
    order.sort((a, b) => a.z - b.z);
    for (const entry of order) drawPlate(entry.index, entry.psi, u, v, axis);
  }

  function frame(now: number): void {
    const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    clock = (clock + dt) % SPIN_SECONDS;

    velX += ((targetX - leanX) * SPRING_K - velX * SPRING_D) * dt;
    velY += ((targetY - leanY) * SPRING_K - velY * SPRING_D) * dt;
    leanX += velX * dt;
    leanY += velY * dt;

    render();
    frameId = requestAnimationFrame(frame);
  }

  function start(): void {
    if (running || disposed || !textures) return;
    running = true;
    last = performance.now();
    frameId = requestAnimationFrame(frame);
  }

  function stop(): void {
    if (!running) return;
    running = false;
    cancelAnimationFrame(frameId);
  }

  function onPointerMove(event: PointerEvent): void {
    const box = canvas.getBoundingClientRect();
    targetX = ((event.clientX - box.left) / box.width) * 2 - 1;
    targetY = ((event.clientY - box.top) / box.height) * 2 - 1;
  }

  function onPointerLeave(): void {
    targetX = 0;
    targetY = 0;
  }

  function onVisibility(): void {
    if (document.hidden) stop();
    else if (visible) start();
  }

  const observer = new IntersectionObserver(
    (entries) => {
      visible = entries.some((entry) => entry.isIntersecting);
      if (visible && !document.hidden) start();
      else stop();
    },
    { rootMargin: "120px" },
  );

  const resizer = new ResizeObserver(() => {
    resize();
    render();
  });

  resize();
  void buildTiles(tiles).then((built) => {
    if (disposed) return;
    textures = built;
    resize();
    render();
    onReady();
    if (visible && !document.hidden) start();
  });

  observer.observe(canvas);
  resizer.observe(canvas);
  window.addEventListener("pointermove", onPointerMove, { passive: true });
  canvas.addEventListener("pointerleave", onPointerLeave);
  document.addEventListener("visibilitychange", onVisibility);

  return () => {
    disposed = true;
    stop();
    observer.disconnect();
    resizer.disconnect();
    window.removeEventListener("pointermove", onPointerMove);
    canvas.removeEventListener("pointerleave", onPointerLeave);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}

export default function RingCanvas({ tiles, onReady }: RingCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    return mount(canvas, ctx, tiles, () => readyRef.current?.());
  }, [tiles]);

  return <canvas ref={canvasRef} className="mkt-ring-canvas" aria-hidden />;
}
