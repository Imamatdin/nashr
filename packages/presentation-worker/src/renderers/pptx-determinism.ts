/**
 * Byte-stable PPTX packaging.
 *
 * PptxGenJS 4.0.1 stamps the wall-clock time into docProps/core.xml
 * (dcterms:created / dcterms:modified) and JSZip stamps every entry with the
 * time it was added, so two renders of one revision never matched byte for
 * byte. Exports are keyed by (revision, format, renderer) and the first
 * registration wins (ADR 0001 §4.3), so correctness does not depend on this;
 * stable bytes just mean a re-render reproduces the same object and leaves no
 * orphan behind. The package is rebuilt with fixed timestamps and entries in
 * sorted order.
 */

import JSZip from 'jszip';

/** The timestamp every Nashr PPTX carries, in core.xml and on every zip entry. */
export const FIXED_PPTX_TIME = new Date('2000-01-01T00:00:00Z');

const CORE_TIMES =
  /(<dcterms:(created|modified) xsi:type="dcterms:W3CDTF">)[^<]*(<\/dcterms:\2>)/g;

export async function normalizePptx(buffer: Buffer): Promise<Buffer> {
  const source = await JSZip.loadAsync(buffer);
  const stamp = FIXED_PPTX_TIME.toISOString().replace(/\.\d{3}Z$/, 'Z');
  const out = new JSZip();
  const names = Object.keys(source.files)
    .filter((name) => !source.files[name]!.dir)
    .sort();
  for (const name of names) {
    const entry = source.files[name]!;
    if (name === 'docProps/core.xml') {
      const xml = await entry.async('string');
      out.file(name, xml.replace(CORE_TIMES, `$1${stamp}$3`), {
        date: FIXED_PPTX_TIME,
        createFolders: false,
      });
      continue;
    }
    out.file(name, await entry.async('uint8array'), {
      date: FIXED_PPTX_TIME,
      createFolders: false,
    });
  }
  return out.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    compressionOptions: { level: 6 },
    platform: 'UNIX',
  });
}
