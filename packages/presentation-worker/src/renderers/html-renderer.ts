/**
 * HtmlRenderer — produces a single self-contained HTML file from a
 * DeckLayout.
 *
 * The output is one HTML document with inline CSS and JS (no external
 * dependencies). It works offline, in Telegram's in-app browser, on
 * desktop, tablet, and phone. It is the primary delivery format and is
 * also what gets screenshot-captured for the studio PPTX and printed to
 * PDF in later tasks.
 *
 * The renderer is dumb: every position, font, and color was decided by
 * the Layout Pass. The renderer's job is to translate SlideLayout
 * objects into HTML+CSS+JS, attach interactive behavior to elements
 * with semantic roles, and provide navigation + viewport scaling.
 */

import { SLIDE_HEIGHT, SLIDE_WIDTH, isPlaceholderImageSrc } from '../constants.js';
import type {
  DeckLayout,
  DeckSpec,
  FontWeight,
  ImageBlock,
  ScrimBlock,
  ShapeBlock,
  SlideLayout,
  TextBlock,
} from '../types.js';

/** Roles whose initial DOM state must be hidden until a click reveals them. */
const HIDDEN_ROLES = new Set([
  'feedback_correct',
  'feedback_wrong',
  'blank_answer',
  'tf_verdict',
  'tf_explanation',
  'debate_framework',
  // match_right is the student's answer column on matching slides — it
  // must stay hidden until they click "Show answer," otherwise the
  // exercise is trivially solvable.
  'match_right',
]);

/** Roles that act as clickable quiz options. */
const OPTION_ROLES = new Set(['option_correct', 'option_wrong']);

export class HtmlRenderer {
  /** Render a complete deck to an HTML string. */
  render(deck: DeckSpec, layout: DeckLayout): string {
    const css = this.buildCSS(deck);
    const slidesHtml = layout.slides
      .map((slide) => this.renderSlide(slide))
      .join('\n');
    const js = this.buildJS(layout);
    return this.assembleDocument(deck, css, slidesHtml, js);
  }

  // -------------------------------------------------------------------------
  // CSS
  // -------------------------------------------------------------------------

  private buildCSS(deck: DeckSpec): string {
    const p = deck.design.palette;
    const headingFamily = this.resolveFontFamily(deck.design.heading_font);
    const bodyFamily = this.resolveFontFamily(deck.design.body_font);
    return `
:root {
  --slide-bg: ${p.background};
  --slide-surface: ${p.surface};
  --slide-text: ${p.text};
  --slide-accent: ${p.accent};
  --slide-text-secondary: ${p.text_secondary};
  --heading-font: ${headingFamily};
  --body-font: ${bodyFamily};
  --slide-width: ${SLIDE_WIDTH};
  --slide-height: ${SLIDE_HEIGHT};
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: #000;
  font-family: var(--body-font);
  -webkit-font-smoothing: antialiased;
}

.deck { position: relative; width: 100vw; height: 100vh; }

.slide {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  display: none;
  overflow: hidden;
}
.slide.active { display: block; }

.slide-inner {
  position: relative;
  width: ${SLIDE_WIDTH}px;
  height: ${SLIDE_HEIGHT}px;
  transform-origin: top left;
  background: var(--slide-bg);
}

.text-block {
  position: absolute;
  overflow: hidden;
  word-wrap: break-word;
  overflow-wrap: break-word;
  z-index: 2;
}

.image-block { position: absolute; overflow: hidden; z-index: 2; }
.image-block img { width: 100%; height: 100%; object-fit: cover; display: block; }
.image-block.contain img { object-fit: contain; }

.bg-image {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  z-index: 0;
  overflow: hidden;
}
.bg-image img { width: 100%; height: 100%; object-fit: cover; display: block; }

.bg-color { position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 0; }

.scrim { position: absolute; z-index: 1; pointer-events: none; }

.shape { position: absolute; z-index: 1; }

.interactive-option {
  cursor: pointer;
  transition: opacity 0.15s ease, color 0.15s ease;
}
.interactive-option:hover { opacity: 0.8; text-decoration: underline; }

.interactive-hidden { display: none; }
.interactive-revealed { display: block; }

.reveal-trigger { cursor: pointer; }
.reveal-trigger:hover { text-decoration: underline; }

.slide-counter {
  position: fixed;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  font-family: var(--body-font);
  font-size: 12px;
  color: var(--slide-text-secondary);
  z-index: 100;
  opacity: 0.6;
  pointer-events: none;
}

.progress-bar {
  position: fixed;
  top: 0; left: 0;
  height: 3px;
  width: 0;
  background: var(--slide-accent);
  z-index: 100;
  transition: width 0.3s ease;
}

@media print {
  .progress-bar, .slide-counter { display: none; }
  .slide { display: block !important; page-break-after: always; }
  .interactive-hidden { display: block !important; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
}
`;
  }

  // -------------------------------------------------------------------------
  // Slide rendering
  // -------------------------------------------------------------------------

  private renderSlide(slide: SlideLayout): string {
    const parts: string[] = [];

    if (slide.background.color) {
      parts.push(
        `<div class="bg-color" style="background:${slide.background.color}"></div>`,
      );
    }
    if (slide.background.image) {
      parts.push(this.renderImageBlock(slide.background.image));
    }
    if (slide.background.scrim) {
      parts.push(this.renderScrim(slide.background.scrim));
    }

    for (const shape of slide.shapes) {
      parts.push(this.renderShape(shape));
    }

    for (const img of slide.imageBlocks) {
      parts.push(this.renderImageBlock(img));
    }

    for (const text of slide.textBlocks) {
      parts.push(this.renderTextBlock(text));
    }

    const isActive = slide.slideIndex === 0 ? ' active' : '';
    return `<section class="slide${isActive}" data-index="${slide.slideIndex}" data-type="${slide.slideType}">
  <div class="slide-inner">
    ${parts.join('\n    ')}
  </div>
</section>`;
  }

  private renderTextBlock(block: TextBlock): string {
    const x = (block.x * SLIDE_WIDTH) / 100;
    const y = (block.y * SLIDE_HEIGHT) / 100;
    const w = (block.w * SLIDE_WIDTH) / 100;
    const h = (block.h * SLIDE_HEIGHT) / 100;

    const styleParts = [
      `left:${x}px`,
      `top:${y}px`,
      `width:${w}px`,
      `height:${h}px`,
      `font-size:${block.fontSize}px`,
      `font-family:${this.resolveFontFamily(block.fontFamily)}`,
      `font-weight:${this.resolveFontWeight(block.fontWeight)}`,
      `font-style:${block.fontStyle}`,
      `color:${block.color}`,
      `text-align:${block.align}`,
      `line-height:${block.lineHeight}`,
    ];

    // Vertical centering within the box is driven by the block (table cells set
    // valign:'middle'); default top-anchoring stays a plain block so every other
    // layout renders exactly as before. text-align keeps horizontal placement.
    if (block.valign === 'middle') {
      styleParts.push('display:flex', 'flex-direction:column', 'justify-content:center');
    }

    const classes = ['text-block'];
    const dataAttrs: string[] = [];

    if (block.role) {
      dataAttrs.push(`data-role="${block.role}"`);
      if (OPTION_ROLES.has(block.role)) classes.push('interactive-option');
      if (HIDDEN_ROLES.has(block.role)) classes.push('interactive-hidden');
      if (block.role === 'reveal_trigger') classes.push('reveal-trigger');
    }

    if (block.groupId) dataAttrs.push(`data-group="${block.groupId}"`);
    if (block.dataIndex !== undefined) {
      dataAttrs.push(`data-index="${block.dataIndex}"`);
    }

    const text = this.escapeHtml(block.text).replace(/\n/g, '<br>');
    const attrs = dataAttrs.length > 0 ? ' ' + dataAttrs.join(' ') : '';
    return `<div class="${classes.join(' ')}" style="${styleParts.join(';')}"${attrs}>${text}</div>`;
  }

  private renderScrim(scrim: ScrimBlock): string {
    const x = (scrim.x * SLIDE_WIDTH) / 100;
    const y = (scrim.y * SLIDE_HEIGHT) / 100;
    const w = (scrim.w * SLIDE_WIDTH) / 100;
    const h = (scrim.h * SLIDE_HEIGHT) / 100;

    const dirMap: Record<ScrimBlock['direction'], string> = {
      'left-to-right': 'to right',
      'right-to-left': 'to left',
      'top-to-bottom': 'to bottom',
      'bottom-to-top': 'to top',
    };
    const dir = dirMap[scrim.direction];
    const rgba = this.hexToRgba(scrim.color, scrim.opacity);

    const style = [
      `left:${x}px`,
      `top:${y}px`,
      `width:${w}px`,
      `height:${h}px`,
      `background:linear-gradient(${dir}, ${rgba}, transparent)`,
    ].join(';');

    return `<div class="scrim" style="${style}"></div>`;
  }

  private renderShape(shape: ShapeBlock): string {
    const x = (shape.x * SLIDE_WIDTH) / 100;
    const y = (shape.y * SLIDE_HEIGHT) / 100;
    const w = (shape.w * SLIDE_WIDTH) / 100;
    const h = (shape.h * SLIDE_HEIGHT) / 100;
    const opacity = shape.opacity ?? 1;

    if (shape.type === 'line') {
      const stroke = shape.stroke ?? '#000';
      const strokeWidth = shape.strokeWidth ?? 2;

      // Diagonal segment (x2/y2 set): rotate a hairline rect from (x,y) to
      // (x2,y2). CSS `line` shapes are otherwise axis-aligned, which would
      // turn a line chart's slopes into flat bars.
      if (shape.x2 !== undefined && shape.y2 !== undefined) {
        const x2 = (shape.x2 * SLIDE_WIDTH) / 100;
        const y2 = (shape.y2 * SLIDE_HEIGHT) / 100;
        const dx = x2 - x;
        const dy = y2 - y;
        const length = Math.hypot(dx, dy);
        const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
        const style = [
          `left:${x}px`,
          `top:${y - strokeWidth / 2}px`,
          `width:${length}px`,
          `height:${strokeWidth}px`,
          `background:${stroke}`,
          `opacity:${opacity}`,
          `transform:rotate(${angle}deg)`,
          `transform-origin:0 50%`,
        ];
        return `<div class="shape" style="${style.join(';')}"></div>`;
      }

      const isHorizontal = w >= h;
      const renderedW = isHorizontal ? w : strokeWidth;
      const renderedH = isHorizontal ? strokeWidth : h;

      const style = [
        `left:${x}px`,
        `top:${y}px`,
        `width:${renderedW}px`,
        `height:${renderedH}px`,
        `opacity:${opacity}`,
      ];

      if (shape.dashArray) {
        const parts = shape.dashArray.split(/\s+/).filter(Boolean);
        const dashSize = parseInt(parts[0] ?? '4', 10) || 4;
        const gapSize = parseInt(parts[1] ?? String(dashSize), 10) || dashSize;
        const total = dashSize + gapSize;
        const gradientDir = isHorizontal ? 'to right' : 'to bottom';
        style.push(
          `background:repeating-linear-gradient(${gradientDir}, ${stroke} 0, ${stroke} ${dashSize}px, transparent ${dashSize}px, transparent ${total}px)`,
        );
      } else {
        style.push(`background:${stroke}`);
      }

      return `<div class="shape" style="${style.join(';')}"></div>`;
    }

    if (shape.type === 'circle') {
      const radius = Math.min(w, h) / 2;
      const style = [
        `left:${x}px`,
        `top:${y}px`,
        `width:${radius * 2}px`,
        `height:${radius * 2}px`,
        `border-radius:50%`,
        `background:${shape.fill ?? 'transparent'}`,
        `opacity:${opacity}`,
      ];
      if (shape.stroke) {
        style.push(`border:${shape.strokeWidth ?? 1}px solid ${shape.stroke}`);
      }
      return `<div class="shape" style="${style.join(';')}"></div>`;
    }

    // rect
    const style = [
      `left:${x}px`,
      `top:${y}px`,
      `width:${w}px`,
      `height:${h}px`,
      `background:${shape.fill ?? 'transparent'}`,
      `opacity:${opacity}`,
    ];
    if (shape.stroke) {
      style.push(`border:${shape.strokeWidth ?? 1}px solid ${shape.stroke}`);
    }
    return `<div class="shape" style="${style.join(';')}"></div>`;
  }

  private renderImageBlock(img: ImageBlock): string {
    const x = (img.x * SLIDE_WIDTH) / 100;
    const y = (img.y * SLIDE_HEIGHT) / 100;
    const w = (img.w * SLIDE_WIDTH) / 100;
    const h = (img.h * SLIDE_HEIGHT) / 100;

    const isBackground = img.isBackground;
    const classes = isBackground
      ? 'image-block bg-image'
      : `image-block${img.objectFit === 'contain' ? ' contain' : ''}`;

    const isPlaceholder = isPlaceholderImageSrc(img.src);

    if (isPlaceholder) {
      const placeholderStyle = isBackground
        ? 'background:var(--slide-surface);display:flex;align-items:center;justify-content:center;'
        : `left:${x}px;top:${y}px;width:${w}px;height:${h}px;background:var(--slide-surface);display:flex;align-items:center;justify-content:center;`;
      return `<div class="${classes}" style="${placeholderStyle}"><span style="color:var(--slide-text-secondary);font-size:14px;font-family:var(--body-font);">[Image]</span></div>`;
    }

    const opacityStyle = img.opacity !== 1 ? `opacity:${img.opacity};` : '';
    const style = isBackground
      ? opacityStyle
      : `left:${x}px;top:${y}px;width:${w}px;height:${h}px;${opacityStyle}`;
    const styleAttr = style ? ` style="${style}"` : '';

    return `<div class="${classes}"${styleAttr}><img src="${this.escapeAttr(img.src)}" alt="" loading="lazy"></div>`;
  }

  // -------------------------------------------------------------------------
  // JavaScript
  // -------------------------------------------------------------------------

  private buildJS(layout: DeckLayout): string {
    return `
(function() {
  'use strict';

  var currentSlide = 0;
  var totalSlides = ${layout.slides.length};
  var slideElements = document.querySelectorAll('.slide');
  var progressBar = document.querySelector('.progress-bar');
  var counter = document.querySelector('.slide-counter');

  function goToSlide(index) {
    if (index < 0 || index >= totalSlides) return;
    if (slideElements[currentSlide]) slideElements[currentSlide].classList.remove('active');
    currentSlide = index;
    if (slideElements[currentSlide]) slideElements[currentSlide].classList.add('active');
    updateProgress();
    updateScale();
  }
  function nextSlide() { goToSlide(currentSlide + 1); }
  function prevSlide() { goToSlide(currentSlide - 1); }

  function updateProgress() {
    if (progressBar) {
      var pct = ((currentSlide + 1) / totalSlides) * 100;
      progressBar.style.width = pct + '%';
    }
    if (counter) {
      counter.textContent = (currentSlide + 1) + ' / ' + totalSlides;
    }
  }

  function updateScale() {
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var scale = Math.min(vw / 1920, vh / 1080);
    var inners = document.querySelectorAll('.slide-inner');
    var offsetX = (vw - 1920 * scale) / 2;
    var offsetY = (vh - 1080 * scale) / 2;
    for (var i = 0; i < inners.length; i++) {
      inners[i].style.transform = 'scale(' + scale + ')';
      inners[i].style.marginLeft = offsetX + 'px';
      inners[i].style.marginTop = offsetY + 'px';
    }
  }

  document.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') {
      e.preventDefault();
      nextSlide();
    } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
      e.preventDefault();
      prevSlide();
    } else if (e.key === 'Home') {
      e.preventDefault();
      goToSlide(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      goToSlide(totalSlides - 1);
    } else if (e.key === 'Escape') {
      e.preventDefault();
    }
  });

  var touchStartX = 0;
  var touchStartY = 0;
  document.addEventListener('touchstart', function(e) {
    touchStartX = e.changedTouches[0].clientX;
    touchStartY = e.changedTouches[0].clientY;
  }, { passive: true });

  document.addEventListener('touchend', function(e) {
    var dx = e.changedTouches[0].clientX - touchStartX;
    var dy = e.changedTouches[0].clientY - touchStartY;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
      if (dx < 0) nextSlide();
      else prevSlide();
    }
  }, { passive: true });

  // Quiz: clicking an option reveals its associated feedback block and locks
  // every option in the same group so the user cannot double-click.
  var options = document.querySelectorAll('.interactive-option');
  for (var oi = 0; oi < options.length; oi++) {
    options[oi].addEventListener('click', function(ev) {
      var el = ev.currentTarget;
      var role = el.getAttribute('data-role');
      var group = el.getAttribute('data-group');
      if (!group) return;
      var slideEl = el.closest('.slide');
      if (!slideEl) return;

      var groupOptions = slideEl.querySelectorAll('[data-group="' + group + '"].interactive-option');
      for (var i = 0; i < groupOptions.length; i++) {
        groupOptions[i].style.pointerEvents = 'none';
        groupOptions[i].style.opacity = '0.5';
      }
      el.style.opacity = '1';
      el.style.fontWeight = 'bold';

      var feedbackSel = role === 'option_correct'
        ? '[data-group="' + group + '"][data-role="feedback_correct"]'
        : '[data-group="' + group + '"][data-role="feedback_wrong"]';
      var feedback = slideEl.querySelectorAll(feedbackSel);
      for (var fi = 0; fi < feedback.length; fi++) {
        feedback[fi].classList.remove('interactive-hidden');
        feedback[fi].classList.add('interactive-revealed');
      }

      if (role === 'option_correct') {
        el.style.color = 'var(--slide-accent)';
      } else {
        el.style.color = '#C0392B';
        var corrects = slideEl.querySelectorAll('[data-group="' + group + '"][data-role="option_correct"]');
        for (var ci = 0; ci < corrects.length; ci++) {
          corrects[ci].style.color = 'var(--slide-accent)';
          corrects[ci].style.fontWeight = 'bold';
          corrects[ci].style.opacity = '1';
        }
      }
    });
  }

  // Reveal trigger: clicking it un-hides every interactive-hidden element
  // on the same slide (matching, fill-blank, true-false, debate).
  var triggers = document.querySelectorAll('.reveal-trigger');
  for (var ti = 0; ti < triggers.length; ti++) {
    triggers[ti].addEventListener('click', function(ev) {
      var trigger = ev.currentTarget;
      var slideEl = trigger.closest('.slide');
      if (!slideEl) return;
      var hidden = slideEl.querySelectorAll('.interactive-hidden');
      for (var hi = 0; hi < hidden.length; hi++) {
        hidden[hi].classList.remove('interactive-hidden');
        hidden[hi].classList.add('interactive-revealed');
      }
      trigger.style.display = 'none';
    });
  }

  updateScale();
  updateProgress();
  window.addEventListener('resize', updateScale);
})();
`;
  }

  // -------------------------------------------------------------------------
  // Document assembly
  // -------------------------------------------------------------------------

  private assembleDocument(
    deck: DeckSpec,
    css: string,
    slidesHtml: string,
    js: string,
  ): string {
    const lang = deck.language ?? 'en';
    const title = this.escapeHtml(deck.title);
    return `<!DOCTYPE html>
<html lang="${lang}" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<style>
${css}
</style>
</head>
<body>
<div class="progress-bar"></div>
<div class="deck" id="deck">
${slidesHtml}
</div>
<div class="slide-counter"></div>
<script>
${js}
</script>
</body>
</html>`;
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * Escape a string that will end up inside a double-quoted HTML
   * attribute value. URLs commonly contain & and may contain " or '.
   */
  private escapeAttr(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;');
  }

  private hexToRgba(hex: string, opacity: number): string {
    const clean = hex.startsWith('#') ? hex.slice(1) : hex;
    if (clean.length !== 6) return `rgba(0,0,0,${opacity})`;
    const r = parseInt(clean.slice(0, 2), 16);
    const g = parseInt(clean.slice(2, 4), 16);
    const b = parseInt(clean.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${opacity})`;
  }

  private resolveFontFamily(font: string): string {
    const lower = font.toLowerCase();
    const isSerif =
      lower.includes('serif') ||
      lower.includes('playfair') ||
      lower.includes('garamond') ||
      lower.includes('baskerville') ||
      lower.includes('cormorant');
    if (isSerif && !lower.includes('sans')) {
      return `'${font}', 'Noto Serif', Georgia, serif`;
    }
    return `'${font}', 'Noto Sans', Arial, sans-serif`;
  }

  private resolveFontWeight(weight: FontWeight): string {
    switch (weight) {
      case 'bold':
        return '700';
      case 'semibold':
        return '600';
      default:
        return '400';
    }
  }
}
