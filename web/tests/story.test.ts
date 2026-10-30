import { readdirSync, readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import type { Manifest } from '../src/manifest';
import { chapterBreaks, chapterOf, inlineParts, parseCard, parseCards, stepProblems, wordCount } from '../src/story';

const manifest = JSON.parse(
  readFileSync(new URL('../e2e/fixtures/data/manifest.json', import.meta.url), 'utf8'),
) as Manifest;

const dir = new URL('../../story/', import.meta.url);
const files = Object.fromEntries(
  readdirSync(dir).filter((f) => f.endsWith('.md')).map((f) => [`../../story/${f}`, readFileSync(new URL(f, dir), 'utf8')]),
);
const steps = parseCards(files);

const CARD = `---
title: Fuel
layer: net_toa
particles: wind100
arrows: on
view: 10, 15, 1.4
---
Some **text**.

A second paragraph.`;

test('a card has its settings in front matter and its text as the body', () => {
  expect(parseCard('01-fuel', CARD)).toEqual({
    id: '01-fuel', title: 'Fuel', layer: 'net_toa', mode: 'today', frame: null, particles: 'wind100',
    arrows: true, panel: false, chapter: null, view: { lng: 10, lat: 15, zoom: 1.4 },
    body: 'Some **text**.\n\nA second paragraph.',
  });
});

test('mode, frame, panel and chapter are read from the front matter', () => {
  const s = parseCard('06-surplus', '---\ntitle: T\nlayer: net_toa\nmode: climate\nframe: 07\nparticles: jet250\npanel: zonal\nchapter: Engine two\n---\nBody.');
  expect(s).toMatchObject({ mode: 'climate', frame: '07', particles: 'jet250', panel: true, chapter: 'Engine two' });
  expect(parseCard('x', '---\ntitle: T\nlayer: olr\nmode: climate\nframe: year\n---\nBody.').frame).toBe('year');
  expect(parseCard('x', '---\ntitle: T\nlayer: olr\nmode: anom\n---\nBody.')).toMatchObject({ mode: 'anom', frame: null });
  expect(parseCard('x', '---\ntitle: T\nlayer: olr\npanel: none\n---\nBody.').panel).toBe(false);
});

test('overlays default to off and the view to the whole world', () => {
  const s = parseCard('x', '---\ntitle: T\nlayer: olr\n---\nBody.');
  expect(s.particles).toBeNull();
  expect(s.arrows).toBe(false);
  expect(s).toMatchObject({ mode: 'today', frame: null, panel: false, chapter: null });
  expect(s.view).toEqual({ lng: 0.25, lat: 20, zoom: 1.4 });
});

test('bad cards are rejected with the card named', () => {
  const bad = (text: string, message: RegExp) => expect(() => parseCard('07-water', text)).toThrow(message);
  bad('title: T\nlayer: olr\n\nBody', /07-water.*front matter/);
  bad('---\ntitle: T\nlayer: olr\nBody', /never closed/);
  bad('---\nlayer: olr\n---\nBody', /needs a title/);
  bad('---\ntitle: T\n---\nBody', /needs a layer/);
  bad('---\ntitle: T\nlayer: olr\n---\n', /needs a body/);
  bad('---\ntitle: T\nlayer: olr\ncolour: red\n---\nBody', /unknown front matter/);
  bad('---\ntitle: T\nlayer: olr\nparticles: wind50\n---\nBody', /particles must be/);
  bad('---\ntitle: T\nlayer: olr\narrows: yes\n---\nBody', /arrows must be/);
  bad('---\ntitle: T\nlayer: olr\nview: 10, 95, 2\n---\nBody', /view must be/);
  bad('---\ntitle: T\nlayer: olr\nview: 10, 20\n---\nBody', /view must be/);
  bad('---\ntitle: T\nlayer: olr\nmode: forever\n---\nBody', /mode must be/);
  bad('---\ntitle: T\nlayer: olr\nmode: climate\n---\nBody', /needs a frame/);
  bad('---\ntitle: T\nlayer: olr\nmode: climate\nframe: 13\n---\nBody', /frame must be/);
  bad('---\ntitle: T\nlayer: olr\nframe: 07\n---\nBody', /only goes with mode: climate/);
  bad('---\ntitle: T\nlayer: olr\npanel: yes\n---\nBody', /panel must be/);
  bad('---\ntitle: T\nlayer: olr\nchapter: \n---\nBody', /chapter must be/);
  bad(`---\ntitle: T\nlayer: olr\nchapter: ${'x'.repeat(25)}\n---\nBody`, /chapter must be/);
});

test('stepProblems names what a card promises that the manifest does not publish', () => {
  const m = {
    built_layers: ['net_toa', 'olr'],
    clim: { layers: ['net_toa'], uv_layers: ['jet250', 'flux_e'], zonal: 'clim/zonal/{frame}.json', period: '1991-2020' },
    layers: {
      net_toa: { modes: ['climate', 'today', 'anom'], default_mode: 'climate', anomaly: true },
      olr: { modes: ['today'], default_mode: 'today', anomaly: false },
      carnot: { modes: ['climate', 'today'], default_mode: 'climate', anomaly: true },
    },
  } as unknown as Manifest;
  const step = (text: string) => parseCard('x', `---\ntitle: T\n${text}\n---\nBody.`);
  expect(stepProblems(step('layer: net_toa\nmode: climate\nframe: year\nparticles: jet250\narrows: on\npanel: zonal'), m)).toEqual([]);
  expect(stepProblems(step('layer: nope'), m)).toEqual(['nope is not a layer']);
  expect(stepProblems(step('layer: carnot'), m)).toEqual(['carnot is not built']);
  expect(stepProblems(step('layer: olr\nmode: climate\nframe: 07'), m)).toEqual(['olr has no climate mode']);
  expect(stepProblems(step('layer: net_toa\nmode: climate\nframe: 07\nparticles: wind10'), m)).toEqual(['no climate mean flow at wind10']);
  expect(stepProblems(step('layer: net_toa\nmode: today\nparticles: wind10\npanel: zonal'), m)).toEqual([]); // Today needs no climate files
  expect(stepProblems(step('layer: net_toa\nmode: climate\nframe: 01\npanel: zonal'), { ...m, clim: { ...m.clim!, zonal: undefined } }))
    .toEqual(['no climate zonal budget']);
});

test('inline Markdown is bold, italic and code only, and other text stays text', () => {
  expect(inlineParts('a **b** c *d* `e` <script>')).toEqual([
    { kind: 'text', text: 'a ' }, { kind: 'strong', text: 'b' }, { kind: 'text', text: ' c ' },
    { kind: 'em', text: 'd' }, { kind: 'text', text: ' ' }, { kind: 'code', text: 'e' },
    { kind: 'text', text: ' <script>' },
  ]);
});

test('the story has twelve cards in order, each 60 to 100 words', () => {
  expect(steps.map((s) => s.id)).toEqual([
    '01-engine', '02-fuel', '03-ceiling', '04-limit', '05-split', '06-surplus', '07-transport', '08-output',
    '09-battery', '10-ocean-share', '11-today', '12-explore',
  ]);
  for (const s of steps) {
    const n = wordCount(s.body);
    expect(n, `${s.id} has ${n} words`).toBeGreaterThanOrEqual(60);
    expect(n, `${s.id} has ${n} words`).toBeLessThanOrEqual(100);
  }
});

test('each step has the layer, mode, frame, overlays, panel and view the proposal lists', () => {
  const row = (s: (typeof steps)[number]) => [
    s.layer, s.mode, s.frame, s.particles, s.arrows, s.panel, s.view.lng, s.view.lat, s.view.zoom,
  ];
  expect(steps.map(row)).toEqual([
    ['net_toa', 'climate', 'year', null, false, false, 10, 15, 1.4],
    ['asr_sfc', 'climate', 'year', null, false, false, 10, 15, 1.4],
    ['carnot', 'climate', 'year', null, false, false, 10, 15, 1.4],
    ['j_ratio', 'climate', 'year', null, false, false, 15, 20, 2.2],
    ['evap_frac', 'climate', 'year', null, false, false, 10, 15, 1.4],
    ['net_toa', 'climate', 'year', null, false, true, 10, 15, 1.4],
    ['div_e', 'climate', 'year', null, true, false, -30, 35, 1.5],
    ['ke_col', 'climate', '01', 'jet250', false, false, -30, 40, 1.6],
    ['net_sfc', 'climate', '07', null, false, false, 10, 15, 1.4],
    ['net_sfc', 'climate', 'year', null, false, true, -40, 35, 1.6],
    ['ke_col', 'today', null, 'wind100', false, false, 10, 15, 1.4],
    ['net_toa', 'climate', 'year', null, false, false, 10, 15, 1.4],
  ]);
  expect(new Set(steps.map((s) => s.title)).size).toBe(12);
});

test('the chapters are the opening, three parts of the title, and Today', () => {
  expect(steps.map((s) => s.chapter)).toEqual([
    'Opening', 'Engine one', 'Engine one', 'Engine one', 'Engine one', 'Engine two', 'Engine two',
    'Engine two', 'The ocean', 'The ocean', 'Today', 'Today',
  ]);
  expect(chapterBreaks(steps).filter(Boolean).length).toBe(4);
});

// The e2e fixtures publish only a few layers, so check the cards against the real layer metadata
// of the fixture manifest as if everything were published: a card can't promise a mode, climate
// overlay or panel the pipeline doesn't produce.
test('every card shows something the pipeline publishes', () => {
  const natural = Object.keys(manifest.layers).filter((l) => manifest.layers[l]!.modes?.length);
  const full = {
    ...manifest,
    built_layers: Object.keys(manifest.layers),
    clim: { ...manifest.clim!, layers: natural, uv_layers: ['wind10', 'wind100', 'jet250', 'flux_e'], zonal: 'clim/zonal/{frame}.json' },
  } as Manifest;
  for (const s of steps) expect(stepProblems(s, full), s.id).toEqual([]);
});

test('the numbers the cards quote are the ones checked against the data on 2026-10-30', () => {
  const body = Object.fromEntries(steps.map((s) => [s.id, s.body]));
  expect(body['02-fuel']).toContain('**164 W m⁻²**');
  expect(body['03-ceiling']).toContain('**256 K (−17 °C)**');
  expect(body['06-surplus']).toContain('**31 W m⁻²**');
  expect(body['06-surplus']).toContain('**41 W m⁻²**');
  expect(body['08-output']).toContain('**2.4 W m⁻²**');
});

test('card text is plain: no raw HTML, and titles are short', () => {
  for (const s of steps) {
    expect(s.body).not.toMatch(/[<>]/);
    expect(s.title.length).toBeLessThanOrEqual(24);
  }
});

test('the dots break where the chapter changes, and a step without one stays in the previous chapter', () => {
  const c = (...chapters: (string | null)[]) => chapters.map((chapter) => ({ chapter }));
  expect(chapterBreaks(c('Open', 'One', 'One', 'Two', null, 'Close'))).toEqual([false, true, false, true, false, true]);
  expect(chapterBreaks(c(null, null, null))).toEqual([false, false, false]);
  expect(chapterBreaks(c(null, 'One', 'One'))).toEqual([false, true, false]); // the first named chapter after an unnamed opening
  expect(chapterBreaks([])).toEqual([]);
  expect(chapterOf(c('Open', null, 'One', null), 3)).toBe('One');
  expect(chapterOf(c(null, 'One'), 0)).toBeNull();
});
