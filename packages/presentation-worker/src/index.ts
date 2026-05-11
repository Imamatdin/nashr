/**
 * CLI entry point for the Nashr presentation worker.
 *
 * Usage:
 *   node dist/index.js validate --input deck.json
 *   node dist/index.js layout   --input deck.json [--output layout.json]
 *   node dist/index.js render   --input deck.json --format html --output ./out
 *
 * The input may also be piped on stdin in place of --input:
 *   cat deck.json | node dist/index.js layout
 */

import { readFileSync, writeFileSync } from 'fs';
import { Command } from 'commander';
import { LayoutPass } from './layout-pass.js';
import { validateDeckSpec } from './validators.js';
import type { DeckSpec } from './types.js';

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
  .command('render')
  .description('Render a DeckSpec to HTML / PPTX / PDF (stub for Task 20+)')
  .option('-i, --input <path>', 'Path to DeckSpec JSON file')
  .option('-f, --format <format>', 'Output format: html | pptx_editable | pdf', 'html')
  .option('-o, --output <path>', 'Output directory', './output')
  .action((options: { input?: string; format: string; output: string }) => {
    process.stdout.write(
      `Render command (format=${options.format}, output=${options.output}). ` +
        `Rendering is not yet implemented; use the "layout" command.\n`,
    );
    process.exit(0);
  });

function parseInput(inputPath: string | undefined): unknown {
  const raw = inputPath ? readFileSync(inputPath, 'utf-8') : readFileSync(0, 'utf-8');
  return JSON.parse(raw);
}

program.parse();
