/**
 * INTERACTIVE_QUIZ_MCQ layout.
 *
 * Positions:
 *  - Title/instructions at top.
 *  - Up to 3 questions stacked vertically (28% of slide height per question).
 *    Questions beyond 3 must be split into separate slides upstream; this
 *    layout silently drops the overflow rather than overlap content.
 *  - Each question carries its question text, 3-4 options labelled A) B)
 *    C) D), and two feedback blocks (correct + wrong) positioned in the
 *    block reserved at the bottom of the question slot. The renderer is
 *    expected to keep the feedback blocks hidden until an option is
 *    selected; the Layout Pass only positions them.
 *  - Navigation labels at the bottom edge use the deck's language.
 *
 * Every user-facing string is sourced from `getLabels(deck.language)` so
 * a Russian or Karakalpak deck does not leak English chrome.
 *
 * FROZEN BY DESIGN (not migrated to fitMeasuredStack). `feedback_correct` and
 * `feedback_wrong` are deliberately CO-LOCATED at the same y (`questionY+24`):
 * they are mutually-exclusive overlays — the renderer reveals exactly one per
 * answer and both start hidden. A vertical fit would give them distinct tops
 * and reserve height for invisible content (the data_emphasis "reserved band
 * you must not feed into the fit" trap). Unlike data_emphasis there is no
 * overflow bug to fix here — the fixed Q_BLOCK_H slots fit comfortably — so the
 * frozen slots stay and the feedback overlay co-location is intentional.
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import { getLabels } from '../labels.js';
import type {
  DeckSpec,
  ImageBlock,
  ScrimBlock,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildScrim, buildTextBlock, compose, defaultBackground } from './shared.js';

const FEEDBACK_WRONG_COLOR = '#C0392B';
const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const QUESTIONS_BAND_Y = 14;
const Q_BLOCK_H = 28;
const MAX_QUESTIONS_PER_SLIDE = 3;

export function layoutInteractiveQuiz(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const { design } = deck;
  const labels = getLabels(deck.language);
  const blocks: TextBlock[] = [];

  blocks.push(
    buildTextBlock({
      text: slide.content.title,
      region: TITLE,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'center',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
      role: 'static',
    }),
  );

  const questions = (slide.content.quiz_questions ?? []).slice(0, MAX_QUESTIONS_PER_SLIDE);
  questions.forEach((q, qIdx) => {
    const groupId = `q${qIdx}`;
    const questionY = QUESTIONS_BAND_Y + qIdx * Q_BLOCK_H;

    blocks.push(
      buildTextBlock({
        text: q.question,
        region: { x: 5, y: questionY, w: 90, h: 5 },
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
        role: 'question',
        groupId,
      }),
    );

    q.options.slice(0, 4).forEach((opt, oIdx) => {
      const prefix = String.fromCharCode(65 + oIdx);
      blocks.push(
        buildTextBlock({
          text: `${prefix}) ${opt.text}`,
          region: { x: 8, y: questionY + 7 + oIdx * 5, w: 84, h: 4 },
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text,
          align: 'left',
          tier: FONT_SIZES.body,
          lineHeight: LINE_HEIGHTS.body,
          role: opt.is_correct ? 'option_correct' : 'option_wrong',
          groupId,
          dataIndex: oIdx,
        }),
      );
    });

    blocks.push(
      buildTextBlock({
        text: `${labels.interactive.correct}! ${q.explanation_correct}`,
        region: { x: 5, y: questionY + 24, w: 90, h: 4 },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.accent,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
        role: 'feedback_correct',
        groupId,
      }),
    );

    blocks.push(
      buildTextBlock({
        text: `${labels.interactive.wrong}. ${q.explanation_wrong}`,
        region: { x: 5, y: questionY + 24, w: 90, h: 4 },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: FEEDBACK_WRONG_COLOR,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
        role: 'feedback_wrong',
        groupId,
      }),
    );
  });

  blocks.push(
    buildTextBlock({
      text: labels.nav.back,
      region: { x: 2, y: 93, w: 8, h: 4 },
      fontFamily: design.body_font,
      fontWeight: 'normal',
      color: design.palette.text_secondary,
      align: 'left',
      tier: FONT_SIZES.small,
      lineHeight: LINE_HEIGHTS.caption,
      role: 'nav_label',
    }),
  );

  blocks.push(
    buildTextBlock({
      text: labels.nav.next,
      region: { x: 90, y: 93, w: 8, h: 4 },
      fontFamily: design.body_font,
      fontWeight: 'normal',
      color: design.palette.text_secondary,
      align: 'right',
      tier: FONT_SIZES.small,
      lineHeight: LINE_HEIGHTS.caption,
      role: 'nav_label',
    }),
  );

  const background = buildBackground(slide, deck);
  return compose(slide, blocks, [], [], background);
}

function buildBackground(slide: SlideSpec, deck: DeckSpec): SlideBackground {
  const { design } = deck;
  if (slide.content.background_prompt && slide.content.background_url) {
    const bg: SlideBackground = defaultBackground(design);
    const image: ImageBlock = {
      src: slide.content.background_url,
      x: 0,
      y: 0,
      w: 100,
      h: 100,
      objectFit: 'cover',
      opacity: 1,
      isBackground: true,
    };
    const scrim: ScrimBlock = buildScrim(design, {
      direction: 'top-to-bottom',
      opacity: 0.55,
      x: 0,
      y: 0,
      w: 100,
      h: 100,
    });
    bg.image = image;
    bg.scrim = scrim;
    return bg;
  }
  return { color: design.palette.surface };
}
