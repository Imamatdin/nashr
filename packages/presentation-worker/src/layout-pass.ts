/**
 * Layout Pass.
 *
 * Transforms a DeckSpec (positioning-agnostic editorial output) into a
 * DeckLayout (every text block, image, and shape positioned in slide
 * percentages, ready for the renderer).
 *
 * This file is the dispatcher: it routes each slide to its
 * type-specific function in src/layouts/. The composition rules for
 * each slide type live in that file alone — the dispatcher knows
 * nothing about how a chart slide or a section break gets composed.
 *
 * Every slide type — including the six interactive variants — has its
 * own layout function. No fallback dispatch remains.
 */

import {
  layoutChartData,
  layoutComparison,
  layoutConceptDefinition,
  layoutContentSplit,
  layoutDataEmphasis,
  layoutFlowProcess,
  layoutGalleryPeople,
  layoutInteractiveCategorize,
  layoutInteractiveDebate,
  layoutInteractiveFillBlank,
  layoutInteractiveMatching,
  layoutInteractiveQuiz,
  layoutInteractiveTrueFalse,
  layoutQuotePullquote,
  layoutResourcesLinks,
  layoutSectionBreak,
  layoutSummaryTakeaway,
  layoutTableCompact,
  layoutTeamCredits,
  layoutTimeline,
  layoutTitleHero,
  layoutTypographicKeywords,
} from './layouts/index.js';
import type { DeckLayout, DeckSpec, SlideLayout, SlideSpec } from './types.js';

export class LayoutPass {
  /** Generate layouts for every slide in the deck. */
  layout(deck: DeckSpec): DeckLayout {
    const slides = deck.slides.map((slide) => this.layoutSlide(slide, deck));
    return {
      slides,
      totalOverflows: slides.filter((s) => s.hasOverflow).length,
      totalWordLimitViolations: slides.filter((s) => s.wordCount > s.wordLimit).length,
    };
  }

  /** Dispatch on slide_type to the appropriate per-type layout function. */
  layoutSlide(slide: SlideSpec, deck: DeckSpec): SlideLayout {
    switch (slide.slide_type) {
      case 'title_hero':
        return layoutTitleHero(slide, deck);
      case 'content_split':
        return layoutContentSplit(slide, deck);
      case 'data_emphasis':
        return layoutDataEmphasis(slide, deck);
      case 'section_break':
        return layoutSectionBreak(slide, deck);
      case 'summary_takeaway':
        return layoutSummaryTakeaway(slide, deck);
      case 'quote_pullquote':
        return layoutQuotePullquote(slide, deck);
      case 'gallery_people':
        return layoutGalleryPeople(slide, deck);
      case 'comparison':
        return layoutComparison(slide, deck);
      case 'concept_definition':
        return layoutConceptDefinition(slide, deck);
      case 'typographic_keywords':
        return layoutTypographicKeywords(slide, deck);
      case 'timeline':
        return layoutTimeline(slide, deck);
      case 'flow_process':
        return layoutFlowProcess(slide, deck);
      case 'chart_data':
        return layoutChartData(slide, deck);
      case 'table_compact':
        return layoutTableCompact(slide, deck);
      case 'resources_links':
        return layoutResourcesLinks(slide, deck);
      case 'team_credits':
        return layoutTeamCredits(slide, deck);
      case 'interactive_quiz_mcq':
        return layoutInteractiveQuiz(slide, deck);
      case 'interactive_matching':
        return layoutInteractiveMatching(slide, deck);
      case 'interactive_categorize':
        return layoutInteractiveCategorize(slide, deck);
      case 'interactive_fill_blank':
        return layoutInteractiveFillBlank(slide, deck);
      case 'interactive_true_false':
        return layoutInteractiveTrueFalse(slide, deck);
      case 'interactive_debate':
        return layoutInteractiveDebate(slide, deck);
    }
  }
}
