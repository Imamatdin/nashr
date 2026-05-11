/**
 * DeckSpec JSON validator.
 *
 * Catches malformed payloads at the worker boundary before they reach
 * the Layout Pass. The Python side (pydantic) is the authoritative
 * schema; this validator mirrors its key invariants so an integration
 * test or a hand-crafted CLI payload fails loudly rather than silently
 * producing garbage slides.
 *
 * The validator is intentionally not an exhaustive type check —
 * pydantic does the strict validation. Here we verify the structural
 * shape required by the Layout Pass: a DeckSpec is well-formed enough
 * to dispatch on slide_type and read slide content.
 */

import { ALL_SLIDE_TYPES, type SlideType } from './types.js';

export interface ValidationError {
  path: string;
  message: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
}

const HEX_COLOR_RE = /^#[0-9A-Fa-f]{6}$/;
const SLIDE_TYPE_SET: ReadonlySet<string> = new Set<string>(ALL_SLIDE_TYPES);

export function validateDeckSpec(raw: unknown): ValidationResult {
  const errors: ValidationError[] = [];

  if (!isObject(raw)) {
    return { valid: false, errors: [{ path: '$', message: 'deck must be an object' }] };
  }

  if (typeof raw['project_id'] !== 'string' || (raw['project_id'] as string).length === 0) {
    errors.push({ path: 'project_id', message: 'must be a non-empty string' });
  }
  if (typeof raw['title'] !== 'string' || (raw['title'] as string).length === 0) {
    errors.push({ path: 'title', message: 'must be a non-empty string' });
  }
  if (raw['language'] !== undefined && raw['language'] !== null) {
    if (typeof raw['language'] !== 'string') {
      errors.push({ path: 'language', message: 'must be a string' });
    } else if (!['uz', 'ru', 'en', 'kaa'].includes(raw['language'] as string)) {
      errors.push({ path: 'language', message: 'must be one of uz, ru, en, kaa' });
    }
  }

  validateDesign(raw['design'], errors);
  validateSlides(raw['slides'], errors);

  if (raw['export_formats'] !== undefined) {
    if (!Array.isArray(raw['export_formats'])) {
      errors.push({ path: 'export_formats', message: 'must be an array' });
    } else {
      const allowed = ['html', 'pptx_editable', 'pptx_studio', 'pdf'];
      raw['export_formats'].forEach((fmt: unknown, idx: number) => {
        if (typeof fmt !== 'string' || !allowed.includes(fmt)) {
          errors.push({
            path: `export_formats[${idx}]`,
            message: `must be one of ${allowed.join(', ')}`,
          });
        }
      });
    }
  }

  return { valid: errors.length === 0, errors };
}

function validateDesign(design: unknown, errors: ValidationError[]): void {
  if (design === undefined || design === null) {
    errors.push({ path: 'design', message: 'is required' });
    return;
  }
  if (!isObject(design)) {
    errors.push({ path: 'design', message: 'must be an object' });
    return;
  }

  if (typeof design['mood'] !== 'string') {
    errors.push({ path: 'design.mood', message: 'must be a string' });
  }
  if (typeof design['heading_font'] !== 'string' || (design['heading_font'] as string).length === 0) {
    errors.push({ path: 'design.heading_font', message: 'must be a non-empty string' });
  }
  if (typeof design['body_font'] !== 'string' || (design['body_font'] as string).length === 0) {
    errors.push({ path: 'design.body_font', message: 'must be a non-empty string' });
  }
  if (design['background_treatment'] !== 'dark' && design['background_treatment'] !== 'light') {
    errors.push({
      path: 'design.background_treatment',
      message: 'must be "dark" or "light"',
    });
  }

  const palette = design['palette'];
  if (palette === undefined || palette === null) {
    errors.push({ path: 'design.palette', message: 'is required' });
    return;
  }
  if (!isObject(palette)) {
    errors.push({ path: 'design.palette', message: 'must be an object' });
    return;
  }
  for (const key of ['background', 'surface', 'text', 'accent', 'text_secondary'] as const) {
    const value = palette[key];
    if (typeof value !== 'string') {
      errors.push({ path: `design.palette.${key}`, message: 'must be a string' });
    } else if (!HEX_COLOR_RE.test(value)) {
      errors.push({
        path: `design.palette.${key}`,
        message: 'must match the pattern #RRGGBB',
      });
    }
  }
}

function validateSlides(slides: unknown, errors: ValidationError[]): void {
  if (slides === undefined || slides === null) {
    errors.push({ path: 'slides', message: 'is required' });
    return;
  }
  if (!Array.isArray(slides)) {
    errors.push({ path: 'slides', message: 'must be an array' });
    return;
  }
  if (slides.length === 0) {
    errors.push({ path: 'slides', message: 'must contain at least one slide' });
    return;
  }
  if (slides.length > 50) {
    errors.push({ path: 'slides', message: 'must contain at most 50 slides' });
  }

  slides.forEach((slide: unknown, idx: number) => validateSlide(slide, idx, errors));
}

function validateSlide(slide: unknown, idx: number, errors: ValidationError[]): void {
  const prefix = `slides[${idx}]`;
  if (!isObject(slide)) {
    errors.push({ path: prefix, message: 'must be an object' });
    return;
  }
  if (typeof slide['slide_index'] !== 'number') {
    errors.push({ path: `${prefix}.slide_index`, message: 'must be a number' });
  } else if ((slide['slide_index'] as number) < 0) {
    errors.push({ path: `${prefix}.slide_index`, message: 'must be >= 0' });
  }
  if (typeof slide['slide_type'] !== 'string') {
    errors.push({ path: `${prefix}.slide_type`, message: 'must be a string' });
  } else if (!SLIDE_TYPE_SET.has(slide['slide_type'] as string)) {
    errors.push({
      path: `${prefix}.slide_type`,
      message: `must be a known SlideType, got "${slide['slide_type'] as string}"`,
    });
  }

  if (slide['accent_override'] !== undefined && slide['accent_override'] !== null) {
    if (typeof slide['accent_override'] !== 'string' || !HEX_COLOR_RE.test(slide['accent_override'] as string)) {
      errors.push({
        path: `${prefix}.accent_override`,
        message: 'must match the pattern #RRGGBB or be null',
      });
    }
  }

  const content = slide['content'];
  if (!isObject(content)) {
    errors.push({ path: `${prefix}.content`, message: 'must be an object' });
    return;
  }
  if (typeof content['title'] !== 'string' || (content['title'] as string).length === 0) {
    errors.push({
      path: `${prefix}.content.title`,
      message: 'must be a non-empty string',
    });
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Narrow `slide_type` to the SlideType union. Returns null if invalid.
 * Used by the Layout Pass after validateDeckSpec has already confirmed
 * the value is structurally well-formed.
 */
export function asSlideType(value: string): SlideType | null {
  return SLIDE_TYPE_SET.has(value) ? (value as SlideType) : null;
}
