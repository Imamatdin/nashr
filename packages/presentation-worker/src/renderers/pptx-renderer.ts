/**
 * PptxRenderer — produces an editable .pptx file from a DeckLayout.
 *
 * Every position, font, color, and shape comes through pptxgenjs as a
 * native PowerPoint primitive: text boxes, ellipses, rectangles, lines,
 * raster images. The resulting file is editable in PowerPoint, Google
 * Slides (via import), and LibreOffice Impress.
 *
 * PPTX has no JavaScript and no CSS, so two design decisions follow:
 *
 *  1. Interactive quiz slides navigate via hyperlinks. Each quiz question
 *     yields two additional slides appended to the deck — a "Correct"
 *     feedback slide and a "Wrong" feedback slide — and the option text
 *     blocks are hyperlinked to the matching feedback slide. Feedback
 *     slides link back to the next content slide (correct) or back to the
 *     question (wrong, via "Try again").
 *
 *  2. Non-quiz interactive slides (matching, fill-blank, true-false,
 *     debate) cannot hide and reveal content, so every block is rendered
 *     visible. PPTX is the study-aid mode where students see all answers
 *     at once. The HTML renderer retains the hide/reveal mechanic for the
 *     interactive experience.
 *
 * The Layout Pass produces percentages of slide dimensions; pptxgenjs
 * positions are in inches. SLIDE_W_INCHES / SLIDE_H_INCHES are the 16:9
 * canvas size (13.33" × 7.5") that matches DESIGN-LANGUAGE.md.
 */

import PptxGenJS from 'pptxgenjs';
import { SLIDE_WIDTH, isPlaceholderImageSrc } from '../constants.js';
import { getLabels } from '../labels.js';
import type {
  DeckLayout,
  DeckSpec,
  ImageBlock,
  ScrimBlock,
  ShapeBlock,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';

/** Wrong-answer marker color (matches the HTML renderer's hard-coded value). */
const FEEDBACK_WRONG_COLOR = 'C0392B';
/** Correct-answer marker color used on feedback slides. */
const FEEDBACK_CORRECT_COLOR = '4CAF50';

export class PptxRenderer {
  /** 16:9 canvas in inches. */
  private readonly SLIDE_W_INCHES = 13.33;
  private readonly SLIDE_H_INCHES = 7.5;

  /**
   * Render a complete deck to a PPTX buffer.
   *
   * Implementation is a three-pass build:
   *   1. computeFeedbackMap — work out the 1-based slide number each
   *      quiz option will hyperlink to. Must run before buildSlide
   *      because pptxgenjs does not let us mutate elements after adding
   *      them.
   *   2. buildSlide for every content slide, passing the map so options
   *      can be added with their hyperlinks set up front.
   *   3. buildFeedbackSlides appends the localized feedback slides at
   *      the indices computed in pass 1.
   */
  async render(deck: DeckSpec, layout: DeckLayout): Promise<Buffer> {
    const pptx = new PptxGenJS();
    pptx.author = 'Nashr';
    pptx.title = deck.title;
    pptx.subject = deck.subtitle ?? '';
    pptx.defineLayout({
      name: 'NASHR_16_9',
      width: this.SLIDE_W_INCHES,
      height: this.SLIDE_H_INCHES,
    });
    pptx.layout = 'NASHR_16_9';

    const feedbackMap = this.computeFeedbackMap(deck, layout);

    for (let i = 0; i < layout.slides.length; i++) {
      this.buildSlide(pptx, layout.slides[i]!, deck, i, feedbackMap);
    }

    this.buildFeedbackSlides(pptx, deck, layout, feedbackMap);

    const out = await pptx.write({ outputType: 'nodebuffer' });
    return out as Buffer;
  }

  // -------------------------------------------------------------------------
  // Feedback slide mapping
  // -------------------------------------------------------------------------

  /**
   * Map every quiz question to the 1-based PPTX slide numbers of its
   * correct and wrong feedback slides. The layout pass caps interactive
   * quizzes at 3 questions per slide; we mirror that cap so the count
   * never drifts from what the slide actually contains.
   *
   * Exposed for testability.
   */
  computeFeedbackMap(deck: DeckSpec, layout: DeckLayout): Map<string, number> {
    const map = new Map<string, number>();
    let feedbackSlideNum = layout.slides.length + 1;

    for (let i = 0; i < deck.slides.length; i++) {
      const spec = deck.slides[i]!;
      if (spec.slide_type !== 'interactive_quiz_mcq') continue;
      const questions = (spec.content.quiz_questions ?? []).slice(0, 3);
      for (let q = 0; q < questions.length; q++) {
        map.set(`slide${i}_q${q}_correct`, feedbackSlideNum);
        feedbackSlideNum++;
        map.set(`slide${i}_q${q}_wrong`, feedbackSlideNum);
        feedbackSlideNum++;
      }
    }
    return map;
  }

  // -------------------------------------------------------------------------
  // Slide build
  // -------------------------------------------------------------------------

  private buildSlide(
    pptx: PptxGenJS,
    slideLayout: SlideLayout,
    deck: DeckSpec,
    index: number,
    feedbackMap: Map<string, number>,
  ): void {
    const slide = pptx.addSlide();

    this.applyBackground(slide, slideLayout.background);

    for (const shape of slideLayout.shapes) {
      this.addShape(slide, shape);
    }
    for (const img of slideLayout.imageBlocks) {
      this.addImage(slide, img);
    }
    for (const text of slideLayout.textBlocks) {
      this.addTextBlock(slide, text, index, feedbackMap);
    }

    const slideSpec = deck.slides[index] as SlideSpec | undefined;
    if (slideSpec?.content.speaker_notes) {
      slide.addNotes(slideSpec.content.speaker_notes);
    }
  }

  // -------------------------------------------------------------------------
  // Background
  // -------------------------------------------------------------------------

  private applyBackground(slide: PptxGenJS.Slide, bg: SlideBackground): void {
    const imageSrc = bg.image?.src;
    if (imageSrc && !this.isPlaceholder(imageSrc)) {
      slide.background = { path: imageSrc };
    } else if (bg.color) {
      slide.background = { color: this.stripHash(bg.color) };
    }

    if (bg.scrim) {
      this.addScrim(slide, bg.scrim);
    }
  }

  private addScrim(slide: PptxGenJS.Slide, scrim: ScrimBlock): void {
    // pptxgenjs has no native CSS gradients. We approximate the scrim with a
    // single semi-transparent rectangle in the scrim's nominal color. The
    // visual is a uniform tint instead of a fade — acceptable for v1.
    const transparency = Math.round((1 - scrim.opacity) * 100);
    slide.addShape('rect', {
      x: this.pctToInchesX(scrim.x),
      y: this.pctToInchesY(scrim.y),
      w: this.pctToInchesW(scrim.w),
      h: this.pctToInchesH(scrim.h),
      fill: { color: this.stripHash(scrim.color), transparency },
      line: { color: this.stripHash(scrim.color), width: 0 },
    });
  }

  // -------------------------------------------------------------------------
  // Text
  // -------------------------------------------------------------------------

  private addTextBlock(
    slide: PptxGenJS.Slide,
    block: TextBlock,
    slideIndex: number,
    feedbackMap: Map<string, number>,
  ): void {
    const options: PptxGenJS.TextPropsOptions = {
      x: this.pctToInchesX(block.x),
      y: this.pctToInchesY(block.y),
      w: this.pctToInchesW(block.w),
      h: this.pctToInchesH(block.h),
      fontSize: this.pxToPt(block.fontSize),
      fontFace: block.fontFamily,
      color: this.stripHash(block.color),
      bold: block.fontWeight === 'bold' || block.fontWeight === 'semibold',
      italic: block.fontStyle === 'italic',
      align: block.align,
      valign: block.valign ?? 'top',
      lineSpacingMultiple: block.lineHeight,
      wrap: true,
    };

    if (block.role === 'option_correct' || block.role === 'option_wrong') {
      const targetSlide = this.resolveOptionTarget(block, slideIndex, feedbackMap);
      if (targetSlide !== null) {
        options.hyperlink = { slide: targetSlide };
      }
    }

    slide.addText(block.text, options);
  }

  /**
   * Look up the feedback slide number that an option text block should
   * hyperlink to. Returns null when the block doesn't carry the grouping
   * metadata (defensive — the quiz layout always sets groupId).
   */
  private resolveOptionTarget(
    block: TextBlock,
    slideIndex: number,
    feedbackMap: Map<string, number>,
  ): number | null {
    if (!block.groupId) return null;
    const qIdx = this.parseQuestionIndex(block.groupId);
    if (qIdx === null) return null;
    const suffix = block.role === 'option_correct' ? 'correct' : 'wrong';
    const key = `slide${slideIndex}_q${qIdx}_${suffix}`;
    return feedbackMap.get(key) ?? null;
  }

  /** groupId on quiz slides is "q0", "q1", ... — parse the trailing index. */
  private parseQuestionIndex(groupId: string): number | null {
    const m = groupId.match(/^q(\d+)$/);
    if (!m) return null;
    return parseInt(m[1]!, 10);
  }

  // -------------------------------------------------------------------------
  // Shapes
  // -------------------------------------------------------------------------

  private addShape(slide: PptxGenJS.Slide, shape: ShapeBlock): void {
    const x = this.pctToInchesX(shape.x);
    const y = this.pctToInchesY(shape.y);
    const w = this.pctToInchesW(shape.w);
    const h = this.pctToInchesH(shape.h);
    const opacity = shape.opacity ?? 1;
    const transparency = Math.round((1 - opacity) * 100);

    if (shape.type === 'line') {
      const lineStyle = {
        color: this.stripHash(shape.stroke ?? '000000'),
        width: shape.strokeWidth ?? 1,
        dashType: (shape.dashArray ? 'dash' : 'solid') as 'dash' | 'solid',
      };
      // Diagonal segment (x2/y2 set): emit the bounding box and flip
      // vertically when the slope runs bottom-left → top-right, so the line
      // connects the two real endpoints instead of the box's TL→BR corners.
      if (shape.x2 !== undefined && shape.y2 !== undefined) {
        const bx = Math.min(shape.x, shape.x2);
        const by = Math.min(shape.y, shape.y2);
        const flipV = (shape.x2 - shape.x) * (shape.y2 - shape.y) < 0;
        slide.addShape('line', {
          x: this.pctToInchesX(bx),
          y: this.pctToInchesY(by),
          w: this.pctToInchesW(Math.abs(shape.x2 - shape.x)),
          h: this.pctToInchesH(Math.abs(shape.y2 - shape.y)),
          flipV,
          line: lineStyle,
        });
        return;
      }
      slide.addShape('line', { x, y, w, h, line: lineStyle });
      return;
    }

    if (shape.type === 'circle') {
      const d = Math.min(w, h);
      slide.addShape('ellipse', {
        x,
        y,
        w: d,
        h: d,
        fill: shape.fill
          ? { color: this.stripHash(shape.fill), transparency }
          : { type: 'solid', color: 'FFFFFF', transparency: 100 },
        line: shape.stroke
          ? { color: this.stripHash(shape.stroke), width: shape.strokeWidth ?? 1 }
          : { color: 'FFFFFF', width: 0 },
      });
      return;
    }

    // rect
    slide.addShape('rect', {
      x,
      y,
      w,
      h,
      fill: shape.fill
        ? { color: this.stripHash(shape.fill), transparency }
        : { type: 'solid', color: 'FFFFFF', transparency: 100 },
      line: shape.stroke
        ? { color: this.stripHash(shape.stroke), width: shape.strokeWidth ?? 1 }
        : { color: 'FFFFFF', width: 0 },
    });
  }

  // -------------------------------------------------------------------------
  // Images
  // -------------------------------------------------------------------------

  private addImage(slide: PptxGenJS.Slide, img: ImageBlock): void {
    if (this.isPlaceholder(img.src)) return;

    const x = this.pctToInchesX(img.x);
    const y = this.pctToInchesY(img.y);
    const w = this.pctToInchesW(img.w);
    const h = this.pctToInchesH(img.h);

    slide.addImage({
      path: img.src,
      x,
      y,
      w,
      h,
      sizing: {
        type: img.objectFit === 'contain' ? 'contain' : 'cover',
        w,
        h,
      },
    });
  }

  // -------------------------------------------------------------------------
  // Feedback slides
  // -------------------------------------------------------------------------

  private buildFeedbackSlides(
    pptx: PptxGenJS,
    deck: DeckSpec,
    layout: DeckLayout,
    feedbackMap: Map<string, number>,
  ): void {
    const labels = getLabels(deck.language);

    for (let i = 0; i < deck.slides.length; i++) {
      const spec = deck.slides[i]!;
      if (spec.slide_type !== 'interactive_quiz_mcq') continue;
      const questions = (spec.content.quiz_questions ?? []).slice(0, 3);
      for (let q = 0; q < questions.length; q++) {
        const question = questions[q]!;
        const correctTarget = feedbackMap.get(`slide${i}_q${q}_correct`);
        const wrongTarget = feedbackMap.get(`slide${i}_q${q}_wrong`);
        if (correctTarget === undefined || wrongTarget === undefined) continue;

        // CORRECT slide
        const correctSlide = pptx.addSlide();
        this.applyFeedbackBackground(correctSlide, deck);
        correctSlide.addText(`${labels.interactive.correct}!`, {
          x: 0.5,
          y: 2.5,
          w: this.SLIDE_W_INCHES - 1,
          h: 1,
          fontSize: 36,
          fontFace: deck.design.heading_font,
          color: FEEDBACK_CORRECT_COLOR,
          bold: true,
          align: 'center',
          valign: 'middle',
        });
        correctSlide.addText(question.explanation_correct, {
          x: 0.5,
          y: 3.8,
          w: this.SLIDE_W_INCHES - 1,
          h: 1.2,
          fontSize: 14,
          fontFace: deck.design.body_font,
          color: this.stripHash(deck.design.palette.text),
          align: 'center',
          valign: 'top',
          wrap: true,
        });
        const nextContentSlide = Math.min(i + 2, layout.slides.length);
        correctSlide.addText(`${labels.nav.next} →`, {
          x: this.SLIDE_W_INCHES / 2 - 1.5,
          y: 5.5,
          w: 3,
          h: 0.5,
          fontSize: 12,
          fontFace: deck.design.body_font,
          color: this.stripHash(deck.design.palette.accent),
          align: 'center',
          hyperlink: { slide: nextContentSlide },
        });

        // WRONG slide
        const wrongSlide = pptx.addSlide();
        this.applyFeedbackBackground(wrongSlide, deck);
        wrongSlide.addText(labels.interactive.wrong, {
          x: 0.5,
          y: 2.5,
          w: this.SLIDE_W_INCHES - 1,
          h: 1,
          fontSize: 36,
          fontFace: deck.design.heading_font,
          color: FEEDBACK_WRONG_COLOR,
          bold: true,
          align: 'center',
          valign: 'middle',
        });
        wrongSlide.addText(question.explanation_wrong, {
          x: 0.5,
          y: 3.8,
          w: this.SLIDE_W_INCHES - 1,
          h: 1.2,
          fontSize: 14,
          fontFace: deck.design.body_font,
          color: this.stripHash(deck.design.palette.text),
          align: 'center',
          valign: 'top',
          wrap: true,
        });
        wrongSlide.addText(`← ${labels.interactive.tryAgain}`, {
          x: this.SLIDE_W_INCHES / 2 - 1.5,
          y: 5.5,
          w: 3,
          h: 0.5,
          fontSize: 12,
          fontFace: deck.design.body_font,
          color: this.stripHash(deck.design.palette.accent),
          align: 'center',
          // 1-based slide number of the originating quiz slide.
          hyperlink: { slide: i + 1 },
        });
      }
    }
  }

  private applyFeedbackBackground(slide: PptxGenJS.Slide, deck: DeckSpec): void {
    slide.background = { color: this.stripHash(deck.design.palette.background) };
    slide.addShape('rect', {
      x: 0,
      y: 4.5,
      w: this.SLIDE_W_INCHES,
      h: this.SLIDE_H_INCHES - 4.5,
      fill: { color: this.stripHash(deck.design.palette.surface), transparency: 50 },
      line: { color: 'FFFFFF', width: 0 },
    });
  }

  // -------------------------------------------------------------------------
  // Conversions and helpers
  // -------------------------------------------------------------------------

  pctToInchesX(pct: number): number {
    return (pct / 100) * this.SLIDE_W_INCHES;
  }
  pctToInchesY(pct: number): number {
    return (pct / 100) * this.SLIDE_H_INCHES;
  }
  pctToInchesW(pct: number): number {
    return (pct / 100) * this.SLIDE_W_INCHES;
  }
  pctToInchesH(pct: number): number {
    return (pct / 100) * this.SLIDE_H_INCHES;
  }

  /**
   * Convert a layout px font size to PowerPoint points using the SAME
   * canvas→slide scale the geometry uses.
   *
   * The Layout Pass sizes text on a SLIDE_WIDTH-px canvas and reserves every
   * box as a percentage of that canvas; geometry (pctToInches*) maps the canvas
   * onto a SLIDE_W_INCHES-wide slide. A font must scale by that SAME factor —
   * px / SLIDE_WIDTH * SLIDE_W_INCHES * 72 — or it no longer fits the box the
   * layout measured for it. The previous constant 0.75 (the 96dpi CSS px→pt
   * ratio) silently assumed a 20in-wide canvas; the slide is 13.33in, so every
   * run came out 1.5× too large and tall/wide text (hero stat numbers, long
   * titles) overflowed its box and collided with the block below.
   */
  pxToPt(px: number): number {
    return Math.round((px / SLIDE_WIDTH) * this.SLIDE_W_INCHES * 72);
  }

  stripHash(hex: string): string {
    return hex.startsWith('#') ? hex.slice(1) : hex;
  }

  /**
   * The Layout Pass leaves prompt-shaped strings or absurdly long
   * placeholders in `src` when no real image has been generated. PPTX
   * can't render those — skip them.
   */
  private isPlaceholder(src: string | undefined): boolean {
    return isPlaceholderImageSrc(src);
  }
}
