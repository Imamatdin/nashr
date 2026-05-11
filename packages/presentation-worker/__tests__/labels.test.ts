import { describe, expect, it } from 'vitest';
import { getLabels, type PresentationLabels } from '../src/labels.js';

describe('getLabels', () => {
  it('returns Uzbek labels for "uz"', () => {
    const labels = getLabels('uz');
    expect(labels.nav.next).toBe('Keyingi');
    expect(labels.nav.back).toBe('Orqaga');
    expect(labels.interactive.correct).toBe("To'g'ri");
    expect(labels.content.keyTakeaways).toBe('Asosiy xulosalar');
  });

  it('returns Russian labels for "ru"', () => {
    const labels = getLabels('ru');
    expect(labels.nav.next).toBe('Далее');
    expect(labels.interactive.correct).toBe('Правильно');
    expect(labels.content.references).toBe('Источники');
  });

  it('returns English labels for "en"', () => {
    const labels = getLabels('en');
    expect(labels.nav.next).toBe('Next');
    expect(labels.interactive.correct).toBe('Correct');
    expect(labels.content.keyTakeaways).toBe('Key Takeaways');
  });

  it('returns Karakalpak labels for "kaa"', () => {
    const labels = getLabels('kaa');
    expect(labels.nav.next).toBe('Kelesi');
    expect(labels.nav.back).toBe('Artqa');
    expect(labels.interactive.correct).toBe('Dúrıs');
    expect(labels.interactive.showAnswer).toBe('Jauapdı kórset');
    expect(labels.content.references).toBe('Derekler');
  });

  it('falls back to English for an unknown language code', () => {
    const labels = getLabels('xx');
    expect(labels.nav.next).toBe('Next');
    expect(labels.interactive.correct).toBe('Correct');
  });

  it('is case-insensitive', () => {
    expect(getLabels('UZ')).toEqual(getLabels('uz'));
    expect(getLabels('KAA')).toEqual(getLabels('kaa'));
    expect(getLabels('Ru')).toEqual(getLabels('ru'));
  });

  it('returns a distinct label set for Karakalpak vs Uzbek', () => {
    const uz = getLabels('uz');
    const kaa = getLabels('kaa');
    expect(kaa.nav.next).not.toBe(uz.nav.next);
    expect(kaa.nav.back).not.toBe(uz.nav.back);
    expect(kaa.interactive.correct).not.toBe(uz.interactive.correct);
    expect(kaa.interactive.showAnswer).not.toBe(uz.interactive.showAnswer);
  });

  it('has every label field populated for every supported language', () => {
    const codes = ['uz', 'ru', 'en', 'kaa'];
    for (const code of codes) {
      const labels = getLabels(code);
      assertAllStringsNonEmpty(labels, `getLabels(${code})`);
    }
  });
});

function assertAllStringsNonEmpty(value: PresentationLabels, ctx: string): void {
  const visit = (obj: Record<string, unknown>, path: string): void => {
    for (const [key, val] of Object.entries(obj)) {
      const sub = `${path}.${key}`;
      if (typeof val === 'string') {
        expect(val.length, `${ctx}: ${sub} must be non-empty`).toBeGreaterThan(0);
      } else if (val && typeof val === 'object') {
        visit(val as Record<string, unknown>, sub);
      }
    }
  };
  visit(value as unknown as Record<string, unknown>, ctx);
}
