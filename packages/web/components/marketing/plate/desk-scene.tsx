"use client";

// The desk object on /maqola: a stack of paper under a soft lamp, built from
// three.js primitives. Original work — the ThreeUI series that inspired the
// brief (Halftone Keyboard, Hourglass Loader) is PRO, so it was used as mood
// reference only and none of its source was read or copied.
//
// The composition is a publishing house's desk: a sheet stack on a warm plane,
// one soft key light standing in for the lamp, a slow orbit and a sprung
// pointer lean. Everything is Flexoki paper and ink; nothing here glows.

import { useEffect, useRef } from "react";
import {
  ACESFilmicToneMapping,
  AmbientLight,
  BoxGeometry,
  DirectionalLight,
  Group,
  Mesh,
  MeshStandardMaterial,
  PCFSoftShadowMap,
  PerspectiveCamera,
  PlaneGeometry,
  PointLight,
  Scene,
  ShadowMaterial,
  WebGLRenderer,
} from "three";

const PAPER = 0xfffcf0;
const BASE_50 = 0xf2f0e5;
const BASE_150 = 0xdad8ce;
const INK = 0x1c1b1a;
const GILD = 0xad8301;

const SHEETS = 9;
const SPRING_K = 22;
const SPRING_D = 6.2;

export interface DeskSceneProps {
  onReady?: () => void;
}

function mount(canvas: HTMLCanvasElement, onReady: () => void): () => void {
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setClearAlpha(0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = PCFSoftShadowMap;
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new Scene();
  const camera = new PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0.15, 5.9, 6.5);
  camera.lookAt(0, 0.3, 0);

  // The desk catches shadow and nothing else: a shadow-only material keeps the
  // page's own paper as the ground, so the stack sits ON the site instead of on
  // a grey slab with a visible horizon.
  const desk = new Mesh(new PlaneGeometry(30, 30), new ShadowMaterial({ opacity: 0.16 }));
  desk.rotation.x = -Math.PI / 2;
  desk.receiveShadow = true;
  scene.add(desk);

  const stack = new Group();
  const sheetGeometry = new BoxGeometry(2.62, 0.012, 3.6);
  for (let i = 0; i < SHEETS; i++) {
    const sheet = new Mesh(
      sheetGeometry,
      new MeshStandardMaterial({
        color: i % 4 === 3 ? BASE_50 : PAPER,
        roughness: 0.92,
        metalness: 0,
      }),
    );
    // Hand-stacked, not machine-stacked: each sheet is off by a few millimetres
    // and a degree or two, which is what makes a pile read as paper.
    sheet.position.set(Math.sin(i * 2.399) * 0.055, 0.02 + i * 0.026, Math.cos(i * 1.717) * 0.05);
    sheet.rotation.y = Math.sin(i * 1.31) * 0.035;
    sheet.castShadow = true;
    sheet.receiveShadow = true;
    stack.add(sheet);
  }

  // The top sheet is lifted and turned, the way a page sits when it has just
  // been read: the one asymmetry that stops the stack reading as a slab.
  const top = new Mesh(
    new BoxGeometry(2.62, 0.014, 3.6),
    new MeshStandardMaterial({ color: PAPER, roughness: 0.86, metalness: 0 }),
  );
  top.position.set(0.72, 0.11 + SHEETS * 0.026, -0.34);
  top.rotation.set(0, -0.2, 0.02);
  top.castShadow = true;
  top.receiveShadow = true;
  stack.add(top);

  // A folio rule in gilding on the top sheet: the site's one gold mark, here.
  // What is set on the page: a gilded folio rule, a heading, three lines of
  // body. Flat inlays rather than textures, so the type never renders as blur.
  const rule = new Mesh(
    new BoxGeometry(0.46, 0.004, 0.035),
    new MeshStandardMaterial({ color: GILD, roughness: 0.42, metalness: 0.3 }),
  );
  rule.position.set(-0.66, 0.009, -1.28);
  top.add(rule);

  const heading = new Mesh(
    new BoxGeometry(1.12, 0.004, 0.1),
    new MeshStandardMaterial({ color: INK, roughness: 0.94 }),
  );
  heading.position.set(-0.33, 0.009, -1.02);
  top.add(heading);

  const lineMaterial = new MeshStandardMaterial({ color: BASE_150, roughness: 0.96 });
  for (let i = 0; i < 3; i++) {
    const line = new Mesh(new BoxGeometry(1.86 - i * 0.22, 0.003, 0.055), lineMaterial);
    line.position.set(-0.02 + i * 0.11, 0.008, -0.6 + i * 0.22);
    top.add(line);
  }

  stack.position.y = 0.02;
  scene.add(stack);

  // Light: one soft key standing in for the lamp, a low fill, and a warm point
  // just off frame so the paper edge picks up a highlight.
  const key = new DirectionalLight(0xfff6e0, 1.9);
  key.position.set(-3.8, 6.4, 3.2);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.near = 0.5;
  key.shadow.camera.far = 20;
  key.shadow.camera.left = -6;
  key.shadow.camera.right = 6;
  key.shadow.camera.top = 6;
  key.shadow.camera.bottom = -6;
  key.shadow.radius = 4;
  key.shadow.bias = -0.0008;
  scene.add(key);

  scene.add(new AmbientLight(0xfff8ec, 1.6));

  // The lamp itself stays out of frame; what the composition needs from it is
  // the warm falloff across the top sheet, not a light bulb to look at.
  const lamp = new PointLight(0xffe6b8, 26, 14, 2);
  lamp.position.set(3.1, 2.9, 2.2);
  scene.add(lamp);

  let width = 0;
  let height = 0;
  let frameId = 0;
  let running = false;
  let visible = true;
  let disposed = false;
  let clock = 0;
  let last = 0;

  let targetX = 0;
  let targetY = 0;
  let leanX = 0;
  let leanY = 0;
  let velX = 0;
  let velY = 0;

  function resize(): void {
    const box = canvas.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return;
    width = box.width;
    height = box.height;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function render(): void {
    stack.rotation.y = 0.22 + Math.sin(clock * 0.08) * 0.1 + leanX * 0.13;
    top.position.y = 0.11 + SHEETS * 0.026 + Math.sin(clock * 0.5) * 0.006;
    camera.position.y = 5.9 - leanY * 0.45;
    camera.position.x = 0.2 + leanX * 0.3;
    camera.lookAt(0, 0.3, 0);
    renderer.render(scene, camera);
  }

  function frame(now: number): void {
    const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    clock += dt;
    velX += ((targetX - leanX) * SPRING_K - velX * SPRING_D) * dt;
    velY += ((targetY - leanY) * SPRING_K - velY * SPRING_D) * dt;
    leanX += velX * dt;
    leanY += velY * dt;
    render();
    frameId = requestAnimationFrame(frame);
  }

  function start(): void {
    if (running || disposed) return;
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
  render();
  onReady();
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
    sheetGeometry.dispose();
    renderer.dispose();
  };
}

export default function DeskScene({ onReady }: DeskSceneProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    return mount(canvas, () => readyRef.current?.());
  }, []);

  return <canvas ref={canvasRef} className="mkt-plate-canvas" aria-hidden />;
}
