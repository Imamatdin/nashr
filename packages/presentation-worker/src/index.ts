/**
 * CLI entry point for the Nashr presentation worker.
 *
 * Usage:
 *   node dist/index.js validate --input deck.json
 *   node dist/index.js layout   --input deck.json [--output layout.json]
 *   node dist/index.js render   --input deck.json --format html --output ./out
 *   node dist/index.js render   --input deck.json --format pptx --output ./out
 *   node dist/index.js render   --input deck.json --format pdf  --output ./out
 *
 * The input may also be piped on stdin in place of --input:
 *   cat deck.json | node dist/index.js layout
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import { join } from 'path';
import { Command } from 'commander';
import { QualityAudit } from './audit/index.js';
import { LayoutPass } from './layout-pass.js';
import { HtmlRenderer } from './renderers/index.js';
import { validateDeckSpec } from './validators.js';
import type { AuditReport, DeckSpec } from './types.js';

const program = new Command();

program
  .name('nashr-presentation')
  .description('Nashr presentation rendering engine')
  .version('0.1.0');

program
  .command('validate')
  .description('Validate a DeckSpec JSON file')
  .option('-i, --input <path>', 'Path to DeckSpec JSON file')
  .action((options: { input?: string }) => {
    const deck = parseInput(options.input);
    const result = validateDeckSpec(deck);
    if (result.valid) {
      process.stdout.write('Valid DeckSpec\n');
      process.exit(0);
    }
    process.stderr.write('Invalid DeckSpec:\n');
    for (const err of result.errors) {
      process.stderr.write(`  ${err.path}: ${err.message}\n`);
    }
    process.exit(1);
  });

program
  .command('layout')
  .description('Run the Layout Pass and emit positioned elements as JSON')
  .option('-i, --input <path>', 'Path to DeckSpec JSON file')
  .option('-o, --output <path>', 'Output path for layout JSON (stdout if omitted)')
  .action((options: { input?: string; output?: string }) => {
    const deck = parseInput(options.input);
    const validation = validateDeckSpec(deck);
    if (!validation.valid) {
      process.stderr.write('Invalid DeckSpec:\n');
      for (const err of validation.errors) {
        process.stderr.write(`  ${err.path}: ${err.message}\n`);
      }
      process.exit(1);
    }

    const layoutPass = new LayoutPass();
    const layout = layoutPass.layout(deck as DeckSpec);
    const output = JSON.stringify(layout, null, 2);

    if (options.output) {
      writeFileSync(options.output, output);
      process.stdout.write(`Layout written to ${options.output}\n`);
    } else {
      process.stdout.write(output + '\n');
    }
    process.exit(0);
  });

program
  .command('audit')
  .description('Run quality audit on a DeckSpec')
  .option('-i, --input <path>', 'Path to DeckSpec JSON file')
  .action((options: { input?: string }) => {
    const deck = parseInput(options.input);
    const validation = validateDeckSpec(deck);
    if (!validation.valid) {
      process.stderr.write('Invalid DeckSpec:\n');
      for (const err of validation.errors) {
        process.stderr.write(`  ${err.path}: ${err.message}\n`);
      }
      process.exit(1);
    }
    const typed = deck as DeckSpec;
    const layout = new LayoutPass().layout(typed);
    const report = new QualityAudit().audit(typed, layout);
    printAuditReport(report);
    process.exit(report.is_exportable ? 0 : 1);
  });

program
  .command('render')
  .description('Render a DeckSpec to HTML / PPTX / PDF')
  .option('-i, --input <path>', 'Path to DeckSpec JSON file')
  .option(
    '-f, --format <format>',
    'Output format: html | pptx | pptx_editable | pdf',
    'html',
  )
  .option('-o, --output <path>', 'Output directory', './output')
  .action(async (options: { input?: string; format: string; output: string }) => {
    const deck = parseInput(options.input);
    const validation = validateDeckSpec(deck);
    if (!validation.valid) {
      process.stderr.write('Invalid DeckSpec:\n');
      for (const err of validation.errors) {
        process.stderr.write(`  ${err.path}: ${err.message}\n`);
      }
      process.exit(1);
    }
    const typed = deck as DeckSpec;
    const layout = new LayoutPass().layout(typed);

    const auditReport = new QualityAudit().audit(typed, layout);
    if (!auditReport.is_exportable) {
      process.stderr.write(
        `Quality audit FAILED: ${auditReport.failed} failure(s). Cannot export.\n`,
      );
      const failures = auditReport.results.filter(
        (r) => !r.passed && r.severity === 'fail',
      );
      for (const f of failures) {
        process.stderr.write(`  [${f.check_id}] ${f.message ?? ''}\n`);
      }
      process.exit(1);
    }
    if (auditReport.warnings > 0) {
      process.stderr.write(`Quality audit: ${auditReport.warnings} warning(s)\n`);
    }

    mkdirSync(options.output, { recursive: true });
    const base = sanitizeFilename(typed.title);

    if (options.format === 'html') {
      const html = new HtmlRenderer().render(typed, layout);
      const outPath = join(options.output, `${base}.html`);
      writeFileSync(outPath, html, 'utf-8');
      process.stdout.write(`HTML written to ${outPath}\n`);
      process.stdout.write(
        `Slides: ${layout.slides.length}, Overflows: ${layout.totalOverflows}\n`,
      );
      process.exit(0);
    }

    if (options.format === 'pptx' || options.format === 'pptx_editable') {
      const { PptxRenderer } = await import('./renderers/pptx-renderer.js');
      const buffer = await new PptxRenderer().render(typed, layout);
      const outPath = join(options.output, `${base}.pptx`);
      writeFileSync(outPath, buffer);
      process.stdout.write(`PPTX written to ${outPath}\n`);
      process.exit(0);
    }

    if (options.format === 'pdf') {
      // PDF = the PPTX converted by LibreOffice. One source of truth: the
      // deck the user also receives as .pptx. No headless browser.
      const { PptxRenderer } = await import('./renderers/pptx-renderer.js');
      const { execFileSync } = await import('node:child_process');
      const pptxBuffer = await new PptxRenderer().render(typed, layout);
      const pptxPath = join(options.output, `${base}.pptx`);
      writeFileSync(pptxPath, pptxBuffer);
      execFileSync(
        'soffice',
        ['--headless', '--convert-to', 'pdf', '--outdir', options.output, pptxPath],
        { stdio: 'pipe', timeout: 120000 },
      );
      const outPath = join(options.output, `${base}.pdf`);
      if (!existsSync(outPath)) {
        process.stderr.write('PDF conversion failed: soffice produced no output.\n');
        process.exit(1);
      }
      process.stdout.write(`PDF written to ${outPath}\n`);
      process.exit(0);
    }

    process.stderr.write(
      `Unknown format: ${options.format}. Supported: html, pptx, pdf\n`,
    );
    process.exit(1);
  });

function parseInput(inputPath: string | undefined): unknown {
  const raw = inputPath ? readFileSync(inputPath, 'utf-8') : readFileSync(0, 'utf-8');
  return JSON.parse(raw);
}

/**
 * Strip filesystem-hostile characters from the deck title while keeping
 * Latin Extended (Uzbek/Karakalpak diacritics) and Cyrillic intact.
 * Falls back to "presentation" on an empty result so writeFileSync never
 * receives just ".pptx".
 */
function sanitizeFilename(title: string): string {
  return (
    title
      .replace(/[^a-zA-Z0-9Ѐ-ӿĀ-ɏ\s]/g, '')
      .replace(/\s+/g, '_')
      .slice(0, 60) || 'presentation'
  );
}

function printAuditReport(report: AuditReport): void {
  const lines: string[] = [];
  lines.push('');
  lines.push('Quality Audit Report');
  lines.push('====================');
  lines.push(`Total checks: ${report.total_checks}`);
  lines.push(`Passed: ${report.passed}`);
  lines.push(`Failed: ${report.failed}`);
  lines.push(`Warnings: ${report.warnings}`);
  lines.push(`Exportable: ${report.is_exportable ? 'YES' : 'NO'}`);
  lines.push('');

  const failures = report.results.filter((r) => !r.passed && r.severity === 'fail');
  if (failures.length > 0) {
    lines.push('FAILURES (block export):');
    for (const f of failures) {
      const slidePart =
        f.slide_index !== null && f.slide_index !== undefined
          ? ` (slide ${f.slide_index})`
          : '';
      lines.push(`  [${f.check_id}] ${f.check_name}${slidePart}`);
      if (f.message) lines.push(`    ${f.message}`);
      if (f.rule_reference) lines.push(`    Rule: ${f.rule_reference}`);
    }
  }

  const warnings = report.results.filter((r) => !r.passed && r.severity === 'warn');
  if (warnings.length > 0) {
    lines.push('');
    lines.push('WARNINGS:');
    for (const w of warnings) {
      const slidePart =
        w.slide_index !== null && w.slide_index !== undefined
          ? ` (slide ${w.slide_index})`
          : '';
      lines.push(`  [${w.check_id}] ${w.check_name}${slidePart}`);
      if (w.message) lines.push(`    ${w.message}`);
    }
  }

  process.stdout.write(lines.join('\n') + '\n');
}

program.parse();
