import { describe, expect, it } from 'vitest';
import { isPlaceholderImageSrc } from '../src/constants.js';

describe('isPlaceholderImageSrc', () => {
  it('treats a short https URL as a real reference', () => {
    expect(isPlaceholderImageSrc('https://cdn.example.com/a.png')).toBe(false);
  });

  it('treats a long signed URL (>500 chars) as a real reference, not a placeholder', () => {
    const longSigned =
      'https://acct.r2.cloudflarestorage.com/bucket/temp/p/img.png?X-Amz-Signature=' +
      'a'.repeat(700);
    expect(longSigned.length).toBeGreaterThan(500);
    expect(isPlaceholderImageSrc(longSigned)).toBe(false);
  });

  it('treats a file:// path as a real reference', () => {
    expect(isPlaceholderImageSrc('file:///home/u/.nashr/storage/temp/p/img.jpg')).toBe(false);
  });

  it('treats a bracketed prompt string as a placeholder', () => {
    expect(isPlaceholderImageSrc('[a generated portrait of a philosopher]')).toBe(true);
  });

  it('treats long bare prompt text (no scheme) as a placeholder', () => {
    expect(isPlaceholderImageSrc('a very long descriptive prompt '.repeat(40))).toBe(true);
  });

  it('treats empty / missing src as a placeholder', () => {
    expect(isPlaceholderImageSrc('')).toBe(true);
    expect(isPlaceholderImageSrc(undefined)).toBe(true);
    expect(isPlaceholderImageSrc(null)).toBe(true);
  });
});
