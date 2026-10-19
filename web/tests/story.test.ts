import { readdirSync, readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import type { Manifest } from '../src/manifest';
import { inlineParts, parseCard, parseCards, wordCount } from '../src/story';

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
    id: '01-fuel', title: 'Fuel', layer: 'net_toa', particles: 'wind100', arrows: true,
    view: { lng: 10, lat: 15, zoom: 1.4 }, body: 'Some **text**.\n\nA second paragraph.',
  });
});

test('overlays default to off and the view to the whole world', () => {
  const s = parseCard('x', '---\ntitle: T\nlayer: olr\n---\nBody.');
  expect(s.particles).toBeNull();
  expect(s.arrows).toBe(false);
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
});

test('inline Markdown is bold, italic and code only, and other text stays text', () => {
  expect(inlineParts('a **b** c *d* `e` <script>')).toEqual([
    { kind: 'text', text: 'a ' }, { kind: 'strong', text: 'b' }, { kind: 'text', text: ' c ' },
    { kind: 'em', text: 'd' }, { kind: 'text', text: ' ' }, { kind: 'code', text: 'e' },
    { kind: 'text', text: ' <script>' },
  ]);
});

test('the story has nine cards in order, each 60 to 100 words', () => {
  expect(steps.map((s) => s.id)).toEqual([
    '01-fuel', '02-exhaust', '03-ceiling', '04-feedback', '05-split', '06-output', '07-water',
    '08-transport', '09-explore',
  ]);
  for (const s of steps) {
    const n = wordCount(s.body);
    expect(n, `${s.id} has ${n} words`).toBeGreaterThanOrEqual(60);
    expect(n, `${s.id} has ${n} words`).toBeLessThanOrEqual(100);
  }
});

test('every step shows a real layer, and the spec\'s overlays are in the right steps', () => {
  for (const s of steps) expect(manifest.layers[s.layer], `${s.id}: ${s.layer}`).toBeDefined();
  const by = Object.fromEntries(steps.map((s) => [s.id, s]));
  expect(steps.map((s) => s.layer)).toEqual([
    'net_toa', 't_emit', 'carnot', 'j_ratio', 'evap_frac', 'diss_bl', 'precip', 'div_e', 'net_toa',
  ]);
  expect(by['06-output']!.particles).toBe('wind100');
  expect(by['08-transport']!.arrows).toBe(true);
  expect(steps.filter((s) => s.arrows).length).toBe(1);
  expect(new Set(steps.map((s) => s.title)).size).toBe(9);
});

test('card text is plain: no raw HTML, and titles are short', () => {
  for (const s of steps) {
    expect(s.body).not.toMatch(/[<>]/);
    expect(s.title.length).toBeLessThanOrEqual(24);
  }
});
