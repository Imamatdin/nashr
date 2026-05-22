/**
 * Quality audit for Nashr presentations.
 *
 * Runs AFTER the Layout Pass, BEFORE rendering.
 * Checks every slide against design language rules from
 * packages/presentation/DESIGN-LANGUAGE.md (section "Quality audit checklist").
 *
 * FAIL results block export. WARN results are surfaced but don't block.
 * A presentation with 0 FAILs is exportable regardless of warnings.
 *
 * Two emission patterns coexist by intent:
 *  - Per-slide checks (Q1, Q2, Q3) emit one result per slide.
 *  - Whole-deck checks (Q4-Q15) emit one result per violation, or a
 *    single passing sentinel when no violation is found. `total_checks`
 *    therefore varies with slide count; consumers should rely on the
 *    `failed` / `warnings` counters, not the total.
 */

import type {
  AuditCheckResult,
  AuditReport,
  DeckLayout,
  DeckSpec,
  SlideType,
} from '../types.js';
import { WORD_LIMITS } from '../constants.js';

export class QualityAudit {
  /**
   * Fonts that are bundled or reliably available cross-platform.
   * Decks specifying anything else are flagged by Q7 — the renderer
   * may still attempt the font but cannot guarantee fidelity.
   */
  private static readonly SAFE_FONTS = new Set<string>([
    'noto serif',
    'noto sans',
    'inter',
    'georgia',
    'arial',
    'noto serif display',
    'noto sans display',
    'times new roman',
    'helvetica',
    'verdana',
    'tahoma',
    'roboto',
    'open sans',
    'lato',
    'montserrat',
    'playfair display',
    'eb garamond',
    'space grotesk',
    'cormorant garamond',
    'libre baskerville',
    'source sans pro',
    'sora',
    'dm sans',
    'jetbrains mono',
    'geist',
    'geist mono',
    'source serif 4',
    'ibm plex sans',
    'ibm plex serif',
    'lora',
  ]);

  /** Single-word or two-word titles that signal a topic-not-takeaway slide (R08). */
  private static readonly GENERIC_TITLES = new Set<string>([
    'results',
    'methodology',
    'introduction',
    'conclusion',
    'background',
    'discussion',
    'overview',
    'summary',
    'analysis',
    'approach',
    'problem',
    'solution',
    'recommendations',
    'findings',
    'data',
    // Uzbek equivalents
    'natijalar',
    'metodologiya',
    'kirish',
    'xulosa',
    'tahlil',
    // Russian equivalents
    'результаты',
    'методология',
    'введение',
    'заключение',
    'анализ',
  ]);

  /** Slide types that count as data-heavy for the R27 rhythm check. */
  private static readonly DATA_HEAVY_TYPES: ReadonlySet<SlideType> = new Set<SlideType>([
    'data_emphasis',
    'chart_data',
    'table_compact',
  ]);

  /** Run all 15 checks on a deck. */
  audit(deck: DeckSpec, layout: DeckLayout): AuditReport {
    const results: AuditCheckResult[] = [];

    results.push(...this.checkQ1TextOverflow(layout));
    results.push(...this.checkQ2Contrast(deck, layout));
    results.push(...this.checkQ3WordCount(layout));
    results.push(...this.checkQ4ConsecutiveRepeats(deck));
    results.push(...this.checkQ5EmptySlides(layout));
    results.push(...this.checkQ6ImageResolution(layout));
    results.push(...this.checkQ7FontAvailability(deck));
    results.push(...this.checkQ8LanguageConsistency(deck));
    results.push(...this.checkQ9InteractiveCompleteness(deck));
    results.push(...this.checkQ10NavigationLinks(deck));
    results.push(...this.checkQ11NoBoxes(layout));
    results.push(...this.checkQ12TakeawayTitles(deck));
    results.push(...this.checkQ13Diacritics(deck));
    results.push(...this.checkQ14ConsecutiveDataSlides(deck));
    results.push(...this.checkQ15StatVariation(deck));

    const failed = results.filter((r) => !r.passed && r.severity === 'fail').length;
    const warned = results.filter((r) => !r.passed && r.severity === 'warn').length;
    const passed = results.filter((r) => r.passed).length;

    return {
      deck_id: deck.project_id,
      total_checks: results.length,
      passed,
      failed,
      warnings: warned,
      is_exportable: failed === 0,
      results,
    };
  }

  // -------------------------------------------------------------------------
  // Q1: Text overflow (FAIL, R16/R17)
  // -------------------------------------------------------------------------

  private checkQ1TextOverflow(layout: DeckLayout): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];
    for (const slide of layout.slides) {
      const overflowBlocks = slide.textBlocks.filter((b) => b.overflow);
      if (overflowBlocks.length > 0) {
        const blockSummary = overflowBlocks
          .map((b) => `"${b.text.slice(0, 30)}..." at ${b.fontSize}px`)
          .join('; ');
        results.push({
          check_id: 'Q1',
          check_name: 'Text overflow',
          passed: false,
          severity: 'fail',
          slide_index: slide.slideIndex,
          rule_reference: 'R16',
          message:
            `${overflowBlocks.length} text block(s) overflow on slide ${slide.slideIndex}. ` +
            `Blocks: ${blockSummary}`,
        });
      } else {
        results.push({
          check_id: 'Q1',
          check_name: 'Text overflow',
          passed: true,
          severity: 'fail',
          slide_index: slide.slideIndex,
        });
      }
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q2: WCAG AA contrast (FAIL, 4.5:1)
  // -------------------------------------------------------------------------

  private checkQ2Contrast(deck: DeckSpec, layout: DeckLayout): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];
    const paletteBg = deck.design.palette.background;

    for (const slide of layout.slides) {
      const bgColor = slide.background.color ?? paletteBg;
      const effectiveBg = slide.background.scrim
        ? this.blendScrimColor(
            bgColor,
            slide.background.scrim.color,
            slide.background.scrim.opacity,
          )
        : bgColor;

      let worstRatio = Infinity;
      let worstBlock: string | null = null;

      for (const block of slide.textBlocks) {
        const ratio = this.contrastRatio(block.color, effectiveBg);
        if (ratio < worstRatio) {
          worstRatio = ratio;
          worstBlock = block.text.slice(0, 30);
        }
      }

      if (slide.textBlocks.length > 0 && worstRatio < 4.5) {
        results.push({
          check_id: 'Q2',
          check_name: 'WCAG AA contrast',
          passed: false,
          severity: 'fail',
          slide_index: slide.slideIndex,
          rule_reference: 'Baseline',
          message:
            `Contrast ratio ${worstRatio.toFixed(2)}:1 on slide ${slide.slideIndex} ` +
            `for text "${worstBlock}..." (minimum 4.5:1 required)`,
        });
      } else {
        results.push({
          check_id: 'Q2',
          check_name: 'WCAG AA contrast',
          passed: true,
          severity: 'fail',
          slide_index: slide.slideIndex,
        });
      }
    }

    return results;
  }

  /** WCAG 2.0 contrast ratio between two hex colors. */
  contrastRatio(fg: string, bg: string): number {
    const fgL = this.relativeLuminance(fg);
    const bgL = this.relativeLuminance(bg);
    const lighter = Math.max(fgL, bgL);
    const darker = Math.min(fgL, bgL);
    return (lighter + 0.05) / (darker + 0.05);
  }

  /** Relative luminance of a hex color, per WCAG 2.0. */
  relativeLuminance(hex: string): number {
    const [r, g, b] = this.hexToRgbArray(hex).map((c) => {
      const s = c / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  private hexToRgbArray(hex: string): [number, number, number] {
    const h = hex.startsWith('#') ? hex.slice(1) : hex;
    return [
      parseInt(h.slice(0, 2), 16),
      parseInt(h.slice(2, 4), 16),
      parseInt(h.slice(4, 6), 16),
    ];
  }

  /**
   * Approximate the blended color of a scrim over a background. Simple alpha
   * blending: result = scrim * opacity + bg * (1 - opacity). This is a
   * conservative approximation — gradient scrims aren't uniform — but it
   * captures the dominant case (text sitting on the opaque end of the scrim).
   */
  private blendScrimColor(bg: string, scrim: string, opacity: number): string {
    const bgRgb = this.hexToRgbArray(bg);
    const scrimRgb = this.hexToRgbArray(scrim);
    const blended = bgRgb.map((bgC, i) =>
      Math.round(scrimRgb[i] * opacity + bgC * (1 - opacity)),
    );
    return '#' + blended.map((c) => c.toString(16).padStart(2, '0')).join('');
  }

  // -------------------------------------------------------------------------
  // Q3: Word count per slide type (FAIL, R17)
  // -------------------------------------------------------------------------

  private checkQ3WordCount(layout: DeckLayout): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];
    for (const slide of layout.slides) {
      const limit = WORD_LIMITS[slide.slideType] ?? 999;
      if (slide.wordCount > limit) {
        results.push({
          check_id: 'Q3',
          check_name: 'Word count limit',
          passed: false,
          severity: 'warn',
          slide_index: slide.slideIndex,
          rule_reference: 'R17',
          message: `Slide ${slide.slideIndex} (${slide.slideType}): ${slide.wordCount} words, limit ${limit}`,
        });
      } else {
        results.push({
          check_id: 'Q3',
          check_name: 'Word count limit',
          passed: true,
          severity: 'warn',
          slide_index: slide.slideIndex,
        });
      }
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q4: No consecutive layout-type repeats (FAIL, R01)
  // -------------------------------------------------------------------------

  private checkQ4ConsecutiveRepeats(deck: DeckSpec): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];
    for (let i = 1; i < deck.slides.length; i++) {
      const prev = deck.slides[i - 1].slide_type;
      const curr = deck.slides[i].slide_type;
      if (prev === curr) {
        results.push({
          check_id: 'Q4',
          check_name: 'Consecutive layout repeat',
          passed: false,
          severity: 'fail',
          slide_index: i,
          rule_reference: 'R01',
          message: `Slides ${i - 1} and ${i} both use "${curr}"`,
        });
      }
    }
    if (results.length === 0) {
      results.push({
        check_id: 'Q4',
        check_name: 'Consecutive layout repeat',
        passed: true,
        severity: 'fail',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q5: Empty slides (FAIL)
  // -------------------------------------------------------------------------

  private checkQ5EmptySlides(layout: DeckLayout): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];
    for (const slide of layout.slides) {
      const hasContent =
        slide.textBlocks.length > 0 ||
        slide.imageBlocks.length > 0 ||
        slide.shapes.length > 0;
      if (!hasContent) {
        results.push({
          check_id: 'Q5',
          check_name: 'Empty slide',
          passed: false,
          severity: 'fail',
          slide_index: slide.slideIndex,
          message: `Slide ${slide.slideIndex} has no content`,
        });
      }
    }
    if (results.length === 0) {
      results.push({
        check_id: 'Q5',
        check_name: 'Empty slide',
        passed: true,
        severity: 'fail',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q6: Image resolution (WARN, R20)
  // -------------------------------------------------------------------------

  private checkQ6ImageResolution(layout: DeckLayout): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];
    for (const slide of layout.slides) {
      if (slide.background.image) {
        const src = slide.background.image.src;
        if (!src || src.startsWith('[') || src.length > 500) {
          results.push({
            check_id: 'Q6',
            check_name: 'Image resolution',
            passed: false,
            severity: 'warn',
            slide_index: slide.slideIndex,
            rule_reference: 'R20',
            message: `Slide ${slide.slideIndex}: background image is a prompt/placeholder, not a resolved URL`,
          });
        }
      }
    }
    if (results.length === 0) {
      results.push({
        check_id: 'Q6',
        check_name: 'Image resolution',
        passed: true,
        severity: 'warn',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q7: Font availability (FAIL, R50)
  // -------------------------------------------------------------------------

  private checkQ7FontAvailability(deck: DeckSpec): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];
    const fonts: string[] = [deck.design.heading_font, deck.design.body_font];
    if (deck.design.decorative_font) fonts.push(deck.design.decorative_font);

    for (const font of fonts) {
      if (!QualityAudit.SAFE_FONTS.has(font.toLowerCase())) {
        const sample = [...QualityAudit.SAFE_FONTS].slice(0, 5).join(', ');
        results.push({
          check_id: 'Q7',
          check_name: 'Font availability',
          passed: false,
          severity: 'fail',
          rule_reference: 'R50',
          message:
            `Font "${font}" is not in the known-safe list. ` +
            `May not render correctly. Safe fonts: ${sample}...`,
        });
      }
    }
    if (results.length === 0) {
      results.push({
        check_id: 'Q7',
        check_name: 'Font availability',
        passed: true,
        severity: 'fail',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q8: Language consistency (WARN, R49)
  // -------------------------------------------------------------------------

  private checkQ8LanguageConsistency(deck: DeckSpec): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];
    let hasCyrillic = false;
    let hasLatin = false;
    for (const slide of deck.slides) {
      const title = slide.content.title;
      if (/[Ѐ-ӿ]/.test(title)) hasCyrillic = true;
      if (/[a-zA-Z]/.test(title)) hasLatin = true;
    }
    if (hasCyrillic && hasLatin) {
      results.push({
        check_id: 'Q8',
        check_name: 'Language consistency',
        passed: false,
        severity: 'warn',
        rule_reference: 'R49',
        message:
          'Deck mixes Cyrillic and Latin scripts in slide titles. ' +
          'Ensure all content is in one language (citations excepted).',
      });
    } else {
      results.push({
        check_id: 'Q8',
        check_name: 'Language consistency',
        passed: true,
        severity: 'warn',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q9: Interactive completeness (FAIL)
  // -------------------------------------------------------------------------

  private checkQ9InteractiveCompleteness(deck: DeckSpec): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];

    for (let i = 0; i < deck.slides.length; i++) {
      const slide = deck.slides[i];
      const content = slide.content;
      const type = slide.slide_type;

      if (type === 'interactive_quiz_mcq') {
        if (!content.quiz_questions || content.quiz_questions.length === 0) {
          results.push(this.interactiveFail(i, 'Quiz has no questions'));
          continue;
        }
        for (let qIdx = 0; qIdx < content.quiz_questions.length; qIdx++) {
          const q = content.quiz_questions[qIdx];
          if (!q.options || q.options.length < 2) {
            results.push(
              this.interactiveFail(i, `Question ${qIdx} has fewer than 2 options`),
            );
          }
          const hasCorrect = q.options?.some((o) => o.is_correct);
          if (!hasCorrect) {
            results.push(
              this.interactiveFail(i, `Question ${qIdx} has no correct answer marked`),
            );
          }
        }
      }

      if (type === 'interactive_matching') {
        if (!content.matching_pairs || content.matching_pairs.length === 0) {
          results.push(this.interactiveFail(i, 'Matching has no pairs'));
        } else {
          for (const pair of content.matching_pairs) {
            if (!pair.left || !pair.right) {
              results.push(
                this.interactiveFail(
                  i,
                  `Matching pair missing left or right: "${pair.left}" / "${pair.right}"`,
                ),
              );
            }
          }
        }
      }

      if (type === 'interactive_fill_blank') {
        if (!content.fill_blanks || content.fill_blanks.length === 0) {
          results.push(this.interactiveFail(i, 'Fill-blank has no items'));
        } else {
          for (const fb of content.fill_blanks) {
            if (!fb.statement || !fb.answer) {
              results.push(
                this.interactiveFail(i, 'Fill-blank item missing statement or answer'),
              );
            }
          }
        }
      }

      if (type === 'interactive_true_false') {
        if (!content.true_false_items || content.true_false_items.length === 0) {
          results.push(this.interactiveFail(i, 'True-false has no items'));
        } else {
          for (const tf of content.true_false_items) {
            if (!tf.statement || !tf.explanation) {
              results.push(
                this.interactiveFail(
                  i,
                  'True-false item missing statement or explanation',
                ),
              );
            }
          }
        }
      }

      if (type === 'interactive_debate') {
        if (!content.debate_prompt) {
          results.push(this.interactiveFail(i, 'Debate has no prompt'));
        }
        if (!content.debate_options || content.debate_options.length < 2) {
          results.push(this.interactiveFail(i, 'Debate has fewer than 2 positions'));
        }
      }

      if (type === 'interactive_categorize') {
        if (!content.category_labels || content.category_labels.length === 0) {
          results.push(this.interactiveFail(i, 'Categorize has no category labels'));
        }
        if (!content.category_items || content.category_items.length === 0) {
          results.push(this.interactiveFail(i, 'Categorize has no items'));
        }
      }
    }

    if (results.length === 0) {
      results.push({
        check_id: 'Q9',
        check_name: 'Interactive completeness',
        passed: true,
        severity: 'fail',
      });
    }
    return results;
  }

  private interactiveFail(slideIndex: number, message: string): AuditCheckResult {
    return {
      check_id: 'Q9',
      check_name: 'Interactive completeness',
      passed: false,
      severity: 'fail',
      slide_index: slideIndex,
      message,
    };
  }

  // -------------------------------------------------------------------------
  // Q10: Navigation links / quiz feedback completeness (FAIL)
  // -------------------------------------------------------------------------

  private checkQ10NavigationLinks(deck: DeckSpec): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];

    for (let i = 0; i < deck.slides.length; i++) {
      const slide = deck.slides[i];
      if (slide.slide_type !== 'interactive_quiz_mcq') continue;
      if (!slide.content.quiz_questions) continue;

      for (const q of slide.content.quiz_questions) {
        if (!q.explanation_correct) {
          results.push({
            check_id: 'Q10',
            check_name: 'Navigation links',
            passed: false,
            severity: 'fail',
            slide_index: i,
            message: `Quiz question "${q.question.slice(0, 30)}..." missing explanation_correct (needed for feedback slide)`,
          });
        }
        if (!q.explanation_wrong) {
          results.push({
            check_id: 'Q10',
            check_name: 'Navigation links',
            passed: false,
            severity: 'fail',
            slide_index: i,
            message: `Quiz question "${q.question.slice(0, 30)}..." missing explanation_wrong (needed for feedback slide)`,
          });
        }
      }
    }

    if (results.length === 0) {
      results.push({
        check_id: 'Q10',
        check_name: 'Navigation links',
        passed: true,
        severity: 'fail',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q11: No visible boxes/cards (WARN, R40)
  // -------------------------------------------------------------------------

  private checkQ11NoBoxes(layout: DeckLayout): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];

    for (const slide of layout.slides) {
      for (const shape of slide.shapes) {
        if (shape.type !== 'rect') continue;

        const isLarge = shape.w > 30 && shape.h > 20;
        const hasVisibleFill = !!shape.fill && (shape.opacity ?? 1) > 0.15;
        const hasVisibleBorder = !!shape.stroke && (shape.strokeWidth ?? 0) > 1;

        if (isLarge && (hasVisibleFill || hasVisibleBorder)) {
          results.push({
            check_id: 'Q11',
            check_name: 'No visible boxes',
            passed: false,
            severity: 'warn',
            slide_index: slide.slideIndex,
            rule_reference: 'R40',
            message:
              `Slide ${slide.slideIndex}: rectangle at (${shape.x}%, ${shape.y}%) ` +
              `size ${shape.w}%×${shape.h}% with opacity ${shape.opacity} looks like a card container`,
          });
        }
      }
    }

    if (results.length === 0) {
      results.push({
        check_id: 'Q11',
        check_name: 'No visible boxes',
        passed: true,
        severity: 'warn',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q12: Takeaway titles (WARN, R08)
  // -------------------------------------------------------------------------

  private checkQ12TakeawayTitles(deck: DeckSpec): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];

    for (let i = 0; i < deck.slides.length; i++) {
      const slide = deck.slides[i];
      if (slide.slide_type === 'section_break') continue;
      if (slide.slide_type.startsWith('interactive_')) continue;

      const title = slide.content.title.trim().toLowerCase();
      const words = title.split(/\s+/);
      if (words.length <= 2 && QualityAudit.GENERIC_TITLES.has(title)) {
        results.push({
          check_id: 'Q12',
          check_name: 'Takeaway titles',
          passed: false,
          severity: 'warn',
          slide_index: i,
          rule_reference: 'R08',
          message:
            `Slide ${i} title "${slide.content.title}" is a generic topic label. ` +
            `Titles should state the takeaway, e.g. "GDP grew 5.6% in 2023" not "Results"`,
        });
      }
    }

    if (results.length === 0) {
      results.push({
        check_id: 'Q12',
        check_name: 'Takeaway titles',
        passed: true,
        severity: 'warn',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q13: Diacritics (FAIL, R50)
  // -------------------------------------------------------------------------

  private checkQ13Diacritics(deck: DeckSpec): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];

    if (deck.language === 'kaa') {
      const kaaChars = /[áóúńǵışÁÓÚŃǴIŞ]/;
      const allTitles = deck.slides.map((s) => s.content.title).join(' ');
      if (!kaaChars.test(allTitles)) {
        results.push({
          check_id: 'Q13',
          check_name: 'Diacritics',
          passed: false,
          severity: 'fail',
          rule_reference: 'R50',
          message:
            'Deck language is Karakalpak (kaa) but no Karakalpak diacritics found in titles. ' +
            'Content may be in the wrong language.',
        });
      }
    }

    if (results.length === 0) {
      results.push({
        check_id: 'Q13',
        check_name: 'Diacritics',
        passed: true,
        severity: 'fail',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q14: Consecutive data-heavy slides (WARN, R27)
  // -------------------------------------------------------------------------

  private checkQ14ConsecutiveDataSlides(deck: DeckSpec): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];

    for (let i = 1; i < deck.slides.length; i++) {
      const prev = deck.slides[i - 1].slide_type;
      const curr = deck.slides[i].slide_type;
      if (
        QualityAudit.DATA_HEAVY_TYPES.has(prev) &&
        QualityAudit.DATA_HEAVY_TYPES.has(curr)
      ) {
        results.push({
          check_id: 'Q14',
          check_name: 'Consecutive data slides',
          passed: false,
          severity: 'warn',
          slide_index: i,
          rule_reference: 'R27',
          message: `Slides ${i - 1} (${prev}) and ${i} (${curr}) are both data-heavy. Insert a breathing slide between them.`,
        });
      }
    }

    if (results.length === 0) {
      results.push({
        check_id: 'Q14',
        check_name: 'Consecutive data slides',
        passed: true,
        severity: 'warn',
      });
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Q15: Stat variation (WARN, R06 DATA_EMPHASIS 3+ stats)
  // -------------------------------------------------------------------------

  private checkQ15StatVariation(deck: DeckSpec): AuditCheckResult[] {
    const results: AuditCheckResult[] = [];

    for (let i = 0; i < deck.slides.length; i++) {
      const slide = deck.slides[i];
      if (slide.slide_type !== 'data_emphasis') continue;
      if (!slide.content.stats || slide.content.stats.length < 3) continue;

      const stats = slide.content.stats;
      const hasHighlight = stats.some((s) => s.highlight);
      const hasTrend = stats.some((s) => !!s.trend);
      const hasComparison = stats.some((s) => !!s.comparison);
      const variationCount = [hasHighlight, hasTrend, hasComparison].filter(Boolean).length;

      if (variationCount === 0) {
        results.push({
          check_id: 'Q15',
          check_name: 'Stat variation',
          passed: false,
          severity: 'warn',
          slide_index: i,
          rule_reference: 'R06',
          message:
            `Slide ${i}: DATA_EMPHASIS with ${stats.length} stats but no variation ` +
            `(no highlights, no trends, no comparisons). Add at least one highlight or trend indicator.`,
        });
      }
    }

    if (results.length === 0) {
      results.push({
        check_id: 'Q15',
        check_name: 'Stat variation',
        passed: true,
        severity: 'warn',
      });
    }
    return results;
  }
}
