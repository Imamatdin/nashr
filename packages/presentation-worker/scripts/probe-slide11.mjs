/**
 * Probe: reproduce slide-11 Q1 overflow with a bar-with-zero-annotation
 * chart whose labels look like "0% waste heat recovered ..." (as in the
 * live sCO2 regen). Prints the failing audit lines and the overflowing
 * blocks' text+fontSize+region so we can identify the real culprit.
 */
import { LayoutPass } from '../dist/layout-pass.js';
import { QualityAudit } from '../dist/audit/index.js';

const design = {
  mood: 'bold_technical',
  palette: {
    background: '#0D0D12',
    surface: '#1A1A22',
    text: '#F5F0E8',
    accent: '#E8553A',
    text_secondary: '#A89F91',
  },
  heading_font: 'Inter',
  body_font: 'Inter',
  decorative_font: null,
  image_style_prefix: 'technical diagram',
  background_treatment: 'dark',
};

const deck = {
  project_id: 'sco2-probe',
  title: 'Probe',
  language: 'en',
  created_at: '2026-05-27T00:00:00Z',
  design,
  interview: {},
  export_formats: ['html'],
  slides: [
    {
      slide_index: 11,
      slide_type: 'chart_data',
      source_claim_ids: [],
      content: {
        title: 'Most cooling stacks throw their waste heat away',
        chart_type: 'bar',
        chart_series: [
          { label: 'Air cooling (min)',   value: 0,  unit: '% waste heat recovered' },
          { label: 'Liquid cooling (min)', value: 0, unit: '% waste heat recovered' },
          { label: 'sCO₂ (min)',          value: 5,  unit: '% waste heat recovered' },
          { label: 'sCO₂ (max)',          value: 20, unit: '% waste heat recovered' },
        ],
      },
    },
    {
      slide_index: 12,
      slide_type: 'flow_process',
      source_claim_ids: [],
      content: {
        title: 'How the sCO2 stack moves heat from die to ambient',
        steps: [
          { label: 'Capture stage in the microchannel manifold', description: '0% waste heat recovered in evaporative racks — sCO2 microchannels lift heat off the silicon die at saturation and condense it in the next stage.' },
          { label: 'Vapour transport over the rejection stack', description: 'Saturated supercritical CO2 carries the load up the rejection stack at near-isothermal pressure across the array of dry coolers.' },
          { label: 'Condensation reject to ambient air', description: 'Dry coolers reject heat to ambient without water evaporation, even at 35°C ambient inlet conditions across desert summer climates.' },
          { label: 'Pump return through the working loop', description: 'A diaphragm pump cycles the working fluid back to the racks at 80 bar with subsonic flow and minimal turbine loss.' },
          { label: 'PID control across saturation states', description: 'PID controllers maintain stable saturation across the array, balancing inlet temperature with valve pressure across 80-120 bar of supercritical state.' },
        ],
      },
    },
    {
      slide_index: 13,
      slide_type: 'data_emphasis',
      source_claim_ids: [],
      content: {
        title: 'sCO2 against the industry baseline',
        stats: [
          { value: '1.58', unit: 'PUE', label: 'Power Usage Effectiveness across rack array', highlight: true, comparison: 'vs 2.0 industry average reported by Uptime Institute 2025' },
          { value: '94.4', unit: '%', label: 'Water savings versus evaporative cooling tower', comparison: 'vs typical evaporative tower with 1.4 L/kWh evaporation' },
          { value: '12', unit: 'MW', label: 'Rack-scale cooling capacity per loop manifold', comparison: '1.4 kW/L sustained supercritical coolant flux at 80 bar' },
        ],
      },
    },
    {
      slide_index: 14,
      slide_type: 'data_emphasis',
      source_claim_ids: [],
      content: {
        title: 'sCO2 hero',
        stats: [
          { value: '94.4', unit: 'percent', label: 'Water savings compared to industry baseline evaporative cooling tower across all measured climate zones', highlight: true, comparison: 'Independent measurement by NREL across summer-winter delta in a desert climate footprint over 18 months' },
        ],
      },
    },
    {
      slide_index: 15,
      slide_type: 'chart_data',
      source_claim_ids: [],
      content: {
        title: 'sCO2 PUE beats every comparable cooling approach',
        chart_type: 'bar',
        chart_series: [
          { label: 'Air cooled rack', value: 1.6, unit: 'PUE' },
          { label: 'Liquid loop (single phase)', value: 1.45, unit: 'PUE' },
          { label: 'Two-phase cold plate', value: 1.3, unit: 'PUE' },
          { label: 'sCO2 closed loop', value: 1.08, unit: 'PUE' },
        ],
      },
    },
  ],
};

const layout = new LayoutPass().layout(deck);

for (const slide of layout.slides) {
  const overflow = slide.textBlocks.filter((b) => b.overflow);
  console.log(`\n=== slide ${slide.slideIndex} (${slide.slideType}) overflowing=${overflow.length} ===`);
  for (const b of overflow) {
    console.log(`  !! text=${JSON.stringify(b.text.slice(0, 60))} fs=${b.fontSize} x=${b.x.toFixed(2)} y=${b.y.toFixed(2)} w=${b.w.toFixed(2)} h=${b.h.toFixed(2)} measured=${b.measuredHeightPct.toFixed(2)}`);
  }
  if (slide.slideType === 'chart_data' && slide.slideIndex === 11) {
    console.log('  chart-11 value-label sizes:');
    for (const b of slide.textBlocks) {
      if (b.text.includes('waste heat')) {
        console.log(`    fs=${b.fontSize} text=${JSON.stringify(b.text)} (h=${b.h.toFixed(2)})`);
      }
    }
  }
  if (slide.slideType === 'data_emphasis') {
    const numberBlocks = slide.textBlocks.filter((b) => /^\d/.test(b.text) && !b.text.includes('waste'));
    if (numberBlocks.length > 0) {
      const sizes = numberBlocks.slice(0, 4).map((b) => b.fontSize);
      console.log(`  data_emphasis number sizes: ${sizes.join(', ')}`);
    }
  }
}

const report = new QualityAudit().audit(deck, layout);
console.log('\naudit fails:');
for (const r of report.results) {
  if (!r.passed) console.log(`  [${r.check_id}] slide=${r.slide_index} ${r.message}`);
}
console.log(`\nis_exportable=${report.is_exportable} failed=${report.failed}`);
