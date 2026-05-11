/**
 * Per-slide-type layout functions, re-exported.
 *
 * Each layout function takes a SlideSpec + DeckSpec and returns a
 * fully positioned SlideLayout. The Layout Pass dispatcher in
 * layout-pass.ts looks up the right function by slide_type and calls
 * it; everything else (deck-wide aggregation, fallback wiring) lives
 * in the dispatcher, not in the layout modules themselves.
 */

export { layoutTitleHero } from './title-hero.js';
export { layoutContentSplit } from './content-split.js';
export { layoutDataEmphasis } from './data-emphasis.js';
export { layoutSectionBreak } from './section-break.js';
export { layoutSummaryTakeaway } from './summary-takeaway.js';
export { layoutQuotePullquote } from './quote-pullquote.js';
export { layoutGalleryPeople } from './gallery-people.js';
export { layoutComparison } from './comparison.js';
export { layoutConceptDefinition } from './concept-definition.js';
export { layoutTypographicKeywords } from './typographic-keywords.js';
export { layoutTimeline } from './timeline.js';
export { layoutFlowProcess } from './flow-process.js';
export { layoutChartData } from './chart-data.js';
export { layoutTableCompact } from './table-compact.js';
export { layoutResourcesLinks } from './resources-links.js';
export { layoutTeamCredits } from './team-credits.js';
export { layoutInteractiveQuiz } from './interactive-quiz.js';
export { layoutInteractiveMatching } from './interactive-matching.js';
export { layoutInteractiveCategorize } from './interactive-categorize.js';
export { layoutInteractiveFillBlank } from './interactive-fill-blank.js';
export { layoutInteractiveTrueFalse } from './interactive-true-false.js';
export { layoutInteractiveDebate } from './interactive-debate.js';
