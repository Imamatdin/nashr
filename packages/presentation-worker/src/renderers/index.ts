/**
 * Renderers barrel.
 *
 * Each renderer takes a DeckSpec + DeckLayout and produces an output
 * artifact (HTML string, PPTX buffer, PDF buffer). The Layout Pass
 * decides positioning; renderers translate.
 */

export { HtmlRenderer } from './html-renderer.js';
