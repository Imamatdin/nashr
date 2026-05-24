/**
 * Wire-format and internal types for the Nashr presentation worker.
 *
 * Two distinct naming conventions live in this file by design.
 *
 * INPUT types (DeckSpec, SlideSpec, SlideContent, DesignDirectionSpec, and
 * every content primitive that flows in from the Python backend) use
 * snake_case. They are the JSON contract emitted by pydantic on the Python
 * side; renaming a single key would silently produce `undefined` at runtime
 * rather than a type error.
 *
 * OUTPUT types (SlideLayout, TextBlock, ImageBlock, ShapeBlock, ScrimBlock,
 * DeckLayout, AuditCheckResult, AuditReport) use camelCase. They are
 * internal to the worker and are consumed by the renderer in this same
 * codebase, so they follow idiomatic TypeScript.
 */

// ---------------------------------------------------------------------------
// Enums (string literal unions, kept in lockstep with packages/core/enums.py)
// ---------------------------------------------------------------------------

export type SlideType =
  | 'title_hero'
  | 'concept_definition'
  | 'gallery_people'
  | 'typographic_keywords'
  | 'content_split'
  | 'data_emphasis'
  | 'comparison'
  | 'timeline'
  | 'flow_process'
  | 'quote_pullquote'
  | 'chart_data'
  | 'table_compact'
  | 'section_break'
  | 'summary_takeaway'
  | 'resources_links'
  | 'team_credits'
  | 'interactive_quiz_mcq'
  | 'interactive_matching'
  | 'interactive_categorize'
  | 'interactive_fill_blank'
  | 'interactive_true_false'
  | 'interactive_debate';

export const ALL_SLIDE_TYPES: readonly SlideType[] = [
  'title_hero',
  'concept_definition',
  'gallery_people',
  'typographic_keywords',
  'content_split',
  'data_emphasis',
  'comparison',
  'timeline',
  'flow_process',
  'quote_pullquote',
  'chart_data',
  'table_compact',
  'section_break',
  'summary_takeaway',
  'resources_links',
  'team_credits',
  'interactive_quiz_mcq',
  'interactive_matching',
  'interactive_categorize',
  'interactive_fill_blank',
  'interactive_true_false',
  'interactive_debate',
] as const;

export type PresentationMood =
  | 'warm_historical'
  | 'bold_technical'
  | 'clean_professional'
  | 'calm_medical'
  | 'natural'
  | 'institutional';

export const ALL_MOODS: readonly PresentationMood[] = [
  'warm_historical',
  'bold_technical',
  'clean_professional',
  'calm_medical',
  'natural',
  'institutional',
] as const;

export type BackgroundTreatment = 'dark' | 'light';

export type ExportFormat = 'html' | 'pptx_editable' | 'pptx_studio' | 'pdf';

export type AuditSeverity = 'fail' | 'warn';

export type Language = 'uz' | 'ru' | 'en' | 'kaa';

// ---------------------------------------------------------------------------
// Content primitives (snake_case, wire format)
// ---------------------------------------------------------------------------

export interface StatItem {
  value: string;
  unit: string;
  label: string;
  highlight?: boolean;
  trend?: string | null;
  comparison?: string | null;
}

export interface PersonItem {
  name: string;
  years?: string | null;
  role?: string | null;
  description?: string | null;
  portrait_prompt?: string | null;
  portrait_url?: string | null;
}

export interface KeywordItem {
  term: string;
  explanation: string;
}

export interface ComparisonColumn {
  heading: string;
  points: string[];
  is_preferred?: boolean;
}

export interface TimelineNode {
  date: string;
  label: string;
  portrait_prompt?: string | null;
}

export interface FlowStep {
  label: string;
  description: string;
  icon?: string | null;
}

export interface TableRow {
  cells: string[];
}

export interface ChartSeriesPoint {
  label: string;
  value: number;
  unit?: string | null;
}

export interface QuizOption {
  text: string;
  is_correct: boolean;
}

export interface QuizQuestion {
  question: string;
  options: QuizOption[];
  explanation_correct: string;
  explanation_wrong: string;
}

export interface MatchingPair {
  left: string;
  right: string;
}

export interface CategoryItem {
  term: string;
  category: string;
}

export interface FillBlankItem {
  statement: string;
  answer: string;
}

export interface TrueFalseItem {
  statement: string;
  is_true: boolean;
  explanation: string;
}

export interface DebateOption {
  position: string;
  framework_label: string;
}

export interface ResourceLink {
  name: string;
  description: string;
  url: string;
}

// ---------------------------------------------------------------------------
// Slide content (snake_case)
// ---------------------------------------------------------------------------

export interface SlideContent {
  title: string;
  subtitle?: string | null;
  body_text?: string | null;
  bullets?: string[] | null;
  caption?: string | null;
  source_citation?: string | null;
  stats?: StatItem[] | null;
  people?: PersonItem[] | null;
  keywords?: KeywordItem[] | null;
  left_column?: ComparisonColumn | null;
  right_column?: ComparisonColumn | null;
  timeline_nodes?: TimelineNode[] | null;
  steps?: FlowStep[] | null;
  quote_text?: string | null;
  quote_attribution?: string | null;
  table_headers?: string[] | null;
  table_rows?: TableRow[] | null;
  chart_series?: ChartSeriesPoint[] | null;
  quiz_questions?: QuizQuestion[] | null;
  matching_pairs?: MatchingPair[] | null;
  category_labels?: string[] | null;
  category_items?: CategoryItem[] | null;
  fill_blanks?: FillBlankItem[] | null;
  true_false_items?: TrueFalseItem[] | null;
  debate_prompt?: string | null;
  debate_options?: DebateOption[] | null;
  resources?: ResourceLink[] | null;
  background_prompt?: string | null;
  background_url?: string | null;
  speaker_notes?: string | null;
}

// ---------------------------------------------------------------------------
// Slide and deck spec (snake_case)
// ---------------------------------------------------------------------------

export interface SlideSpec {
  slide_index: number;
  slide_type: SlideType;
  content: SlideContent;
  background_override?: BackgroundTreatment | null;
  accent_override?: string | null;
  source_claim_ids: string[];
  section_name?: string | null;
  narrative_role?: string | null;
}

export interface ColorPalette {
  background: string;
  surface: string;
  text: string;
  accent: string;
  text_secondary: string;
}

export interface DesignDirectionSpec {
  mood: PresentationMood;
  palette: ColorPalette;
  heading_font: string;
  body_font: string;
  decorative_font?: string | null;
  image_style_prefix: string;
  background_treatment: BackgroundTreatment;
}

export interface DeckSpec {
  project_id: string;
  title: string;
  subtitle?: string | null;
  language: Language;
  created_at: string;
  design: DesignDirectionSpec;
  /**
   * Pass-through of PresentationInterviewAnswers from the Python side.
   * The layout pass does not consume any field here; downstream passes may.
   * Keeping it loose avoids coupling this worker to interview enum changes.
   */
  interview: Record<string, unknown>;
  slides: SlideSpec[];
  export_formats: ExportFormat[];
}

// ---------------------------------------------------------------------------
// Layout pass output types (camelCase, internal to worker)
// ---------------------------------------------------------------------------

export type FontWeight = 'normal' | 'bold' | 'semibold';
export type FontStyle = 'normal' | 'italic';
export type TextAlign = 'left' | 'center' | 'right';

/**
 * Semantic role for a text block in an interactive slide.
 * The renderer uses this to attach behavior (click handlers, visibility toggling).
 * Content slides leave the role unset; only interactive layouts emit roles.
 */
export type InteractiveRole =
  | 'question'
  | 'option'
  | 'option_correct'
  | 'option_wrong'
  | 'feedback_correct'
  | 'feedback_wrong'
  | 'match_left'
  | 'match_right'
  | 'match_connector'
  | 'reveal_trigger'
  | 'reveal_content'
  | 'category_label'
  | 'category_item'
  | 'blank_statement'
  | 'blank_answer'
  | 'tf_statement'
  | 'tf_verdict'
  | 'tf_explanation'
  | 'debate_prompt'
  | 'debate_position'
  | 'debate_framework'
  | 'nav_label'
  | 'static';

/** A positioned text block ready for rendering. Coordinates are slide percentages. */
export interface TextBlock {
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
  fontSize: number;
  fontFamily: string;
  fontWeight: FontWeight;
  fontStyle: FontStyle;
  color: string;
  align: TextAlign;
  lineHeight: number;
  overflow: boolean;
  /**
   * Real rendered height of this block as a PERCENTAGE of slide height —
   * the same unit as `y`/`h`. Captured from measureText at construction
   * (measurement.height px ÷ SLIDE_HEIGHT × 100) so stacking layouts can
   * place the next element at the block's *measured* bottom
   * (`y + measuredHeightPct`) instead of a fixed region y, which is what
   * causes a wrapped multi-line title to overlap the element below it.
   * `h` stays the nominal region height for backward compatibility.
   */
  measuredHeightPct: number;
  /** Only set on interactive slides; renderer uses it to attach behavior. */
  role?: InteractiveRole;
  /** Links related interactive elements (e.g. a quiz question + its options + its feedback). */
  groupId?: string;
  /** Index within the group (option 0/1/2/3, matching pair index, etc.). */
  dataIndex?: number;
}

export interface ImageBlock {
  src: string;
  x: number;
  y: number;
  w: number;
  h: number;
  objectFit: 'cover' | 'contain';
  opacity: number;
  isBackground: boolean;
}

export interface ScrimBlock {
  direction: 'left-to-right' | 'right-to-left' | 'top-to-bottom' | 'bottom-to-top';
  color: string;
  opacity: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ShapeBlock {
  type: 'line' | 'circle' | 'rect';
  x: number;
  y: number;
  w: number;
  h: number;
  stroke?: string;
  strokeWidth?: number;
  fill?: string;
  opacity?: number;
  dashArray?: string;
}

export interface SlideBackground {
  color?: string;
  image?: ImageBlock;
  scrim?: ScrimBlock;
}

export interface SlideLayout {
  slideIndex: number;
  slideType: SlideType;
  width: 1920;
  height: 1080;
  background: SlideBackground;
  textBlocks: TextBlock[];
  imageBlocks: ImageBlock[];
  shapes: ShapeBlock[];
  hasOverflow: boolean;
  wordCount: number;
  wordLimit: number;
}

export interface DeckLayout {
  slides: SlideLayout[];
  totalOverflows: number;
  totalWordLimitViolations: number;
}

// ---------------------------------------------------------------------------
// Audit (camelCase wrappers also kept compatible with Python field names)
// ---------------------------------------------------------------------------

export interface AuditCheckResult {
  check_id: string;
  check_name: string;
  passed: boolean;
  severity: AuditSeverity;
  slide_index?: number | null;
  rule_reference?: string | null;
  message?: string | null;
}

export interface AuditReport {
  deck_id: string;
  total_checks: number;
  passed: number;
  failed: number;
  warnings: number;
  is_exportable: boolean;
  results: AuditCheckResult[];
}
