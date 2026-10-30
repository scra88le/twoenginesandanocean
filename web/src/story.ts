// Story mode: the cards of the guided tour (story/NN-*.md at the repo root) and their parsing.
//
// Each card is a small Markdown file with a front matter block that says what the step shows
// (layer, mode and frame, overlays, panel, view) and a body of 60-100 words. The files are bundled at build time, so
// a card can never be out of step with the code that reads it.
import type { Manifest } from './manifest';
import { MODES, availableModes, isFrame, type Frame, type Mode } from './modes';
import { WIND_LEVELS, type WindLevel } from './wind';

export interface StoryView {
  lng: number;
  lat: number;
  zoom: number;
}

export interface StoryStep {
  id: string; // the file name without its extension, e.g. "03-ceiling"
  title: string;
  layer: string;
  mode: Mode; // default today, so cards written before the modes existed still work
  frame: Frame | null; // the Climate frame; set exactly when mode is climate
  particles: WindLevel | null; // null = off; in Climate mode the mean flow at that level
  arrows: boolean;
  panel: boolean; // the zonal budget panel is open
  chapter: string | null; // the progress dots break where this changes
  view: StoryView;
  body: string; // Markdown
}

const DEFAULT_VIEW: StoryView = { lng: 0.25, lat: 20, zoom: 1.4 };
const KEYS = new Set(['title', 'layer', 'mode', 'frame', 'particles', 'arrows', 'panel', 'chapter', 'view']);
const MAX_CHAPTER = 24;

/** Split a card into its front matter (key: value lines between two `---` lines) and body. */
function split(id: string, text: string): { meta: Map<string, string>; body: string } {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  if (lines[0] !== '---') throw new Error(`${id}: a card starts with a --- front matter block`);
  const end = lines.indexOf('---', 1);
  if (end < 0) throw new Error(`${id}: the front matter block is never closed`);
  const meta = new Map<string, string>();
  for (const line of lines.slice(1, end)) {
    if (!line.trim()) continue;
    const at = line.indexOf(':');
    const key = line.slice(0, at).trim();
    if (at < 0 || !KEYS.has(key)) throw new Error(`${id}: unknown front matter line "${line}"`);
    meta.set(key, line.slice(at + 1).trim());
  }
  return { meta, body: lines.slice(end + 1).join('\n').trim() };
}

function parseView(id: string, text: string | undefined): StoryView {
  if (text === undefined) return DEFAULT_VIEW;
  const [lng, lat, zoom] = text.split(',').map((p) => Number(p.trim()));
  const ok = [lng, lat, zoom].every((v) => Number.isFinite(v)) && text.split(',').length === 3;
  if (!ok || Math.abs(lat!) > 85 || Math.abs(lng!) > 360 || zoom! < 0 || zoom! > 12) {
    throw new Error(`${id}: view must be "lng, lat, zoom", got "${text}"`);
  }
  return { lng: lng!, lat: lat!, zoom: zoom! };
}

export function parseCard(id: string, text: string): StoryStep {
  const { meta, body } = split(id, text);
  const title = meta.get('title');
  const layer = meta.get('layer');
  if (!title) throw new Error(`${id}: a card needs a title`);
  if (!layer) throw new Error(`${id}: a card needs a layer`);
  const particles = meta.get('particles') ?? 'off';
  if (particles !== 'off' && !(WIND_LEVELS as readonly string[]).includes(particles)) {
    throw new Error(`${id}: particles must be off or one of ${WIND_LEVELS.join(', ')}`);
  }
  const arrows = meta.get('arrows') ?? 'off';
  if (arrows !== 'on' && arrows !== 'off') throw new Error(`${id}: arrows must be on or off`);
  const mode = meta.get('mode') ?? 'today';
  if (!(MODES as readonly string[]).includes(mode)) throw new Error(`${id}: mode must be one of ${MODES.join(', ')}`);
  const frame = meta.get('frame') ?? null;
  if (frame !== null && !isFrame(frame)) throw new Error(`${id}: frame must be 01 to 12 or year, got "${frame}"`);
  if (mode === 'climate' && frame === null) throw new Error(`${id}: a climate step needs a frame`);
  if (mode !== 'climate' && frame !== null) throw new Error(`${id}: a frame only goes with mode: climate`);
  const panel = meta.get('panel') ?? 'none';
  if (panel !== 'zonal' && panel !== 'none') throw new Error(`${id}: panel must be zonal or none`);
  const chapter = meta.get('chapter') ?? null;
  if (chapter !== null && (!chapter || chapter.length > MAX_CHAPTER)) {
    throw new Error(`${id}: chapter must be 1 to ${MAX_CHAPTER} characters`);
  }
  if (!body) throw new Error(`${id}: a card needs a body`);
  return {
    id,
    title,
    layer,
    mode: mode as Mode,
    frame: frame as Frame | null,
    particles: particles === 'off' ? null : (particles as WindLevel),
    arrows: arrows === 'on',
    panel: panel === 'zonal',
    chapter,
    view: parseView(id, meta.get('view')),
    body,
  };
}

/** Parse the bundled cards (`{ "../../story/01-fuel.md": text, ... }`) in file-name order. */
export function parseCards(files: Record<string, string>): StoryStep[] {
  return Object.keys(files)
    .sort()
    .map((path) => parseCard(path.split('/').pop()!.replace(/\.md$/, ''), files[path]!));
}

/**
 * What stops a step from showing what its card says, given what the manifest publishes: an unknown
 * or unbuilt layer, a mode the layer can't show, or an overlay or panel without its climate files.
 * Empty when the step works. (Used by the tests, so a card can't promise what isn't published.)
 */
export function stepProblems(step: StoryStep, m: Manifest): string[] {
  const out: string[] = [];
  if (!m.layers[step.layer]) return [`${step.layer} is not a layer`];
  if (!m.built_layers.includes(step.layer)) out.push(`${step.layer} is not built`);
  if (!availableModes(m, step.layer).includes(step.mode)) out.push(`${step.layer} has no ${step.mode} mode`);
  if (step.mode === 'climate') {
    const clim = m.clim;
    if (step.particles && !clim?.uv_layers?.includes(step.particles)) out.push(`no climate mean flow at ${step.particles}`);
    if (step.arrows && !clim?.uv_layers?.includes('flux_e')) out.push('no climate transport arrows');
    if (step.panel && !clim?.zonal) out.push('no climate zonal budget');
  }
  return out;
}

/**
 * Where the progress dots break into chapters: `true` for a step whose chapter differs from the
 * previous step's. A step with no `chapter` stays in the previous one; the first step starts the
 * first chapter, which is not a break.
 */
export function chapterBreaks(steps: Pick<StoryStep, 'chapter'>[]): boolean[] {
  let current: string | null = null;
  return steps.map((s, i) => {
    const chapter = s.chapter ?? current;
    const isBreak = i > 0 && chapter !== current;
    current = chapter;
    return isBreak;
  });
}

/** The chapter a step belongs to: its own, else the nearest one before it (null before any). */
export function chapterOf(steps: Pick<StoryStep, 'chapter'>[], index: number): string | null {
  for (let i = index; i >= 0; i--) if (steps[i]?.chapter) return steps[i]!.chapter;
  return null;
}

export const wordCount = (body: string) => body.split(/\s+/).filter(Boolean).length;

// ---- a tiny, safe Markdown subset: paragraphs, **bold**, *italic* and `code` ----------------

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/;

export interface InlinePart {
  kind: 'text' | 'strong' | 'em' | 'code';
  text: string;
}

/** Split a paragraph into plain text and **bold**, *italic* and `code` parts. */
export function inlineParts(text: string): InlinePart[] {
  return text.split(INLINE).filter(Boolean).map((part): InlinePart => {
    if (part.startsWith('**')) return { kind: 'strong', text: part.slice(2, -2) };
    if (part.startsWith('`')) return { kind: 'code', text: part.slice(1, -1) };
    if (part.startsWith('*')) return { kind: 'em', text: part.slice(1, -1) };
    return { kind: 'text', text: part };
  });
}

/** Inline Markdown into DOM nodes. Text is only ever set as text, never as HTML. */
export function inlineNodes(text: string): Node[] {
  return inlineParts(text).map(({ kind, text: t }) => {
    if (kind === 'text') return document.createTextNode(t);
    const el = document.createElement(kind);
    el.textContent = t;
    return el;
  });
}

/** The card body as paragraphs (blank-line separated). */
export function renderBody(body: string): HTMLParagraphElement[] {
  return body.split(/\n\s*\n/).map((para) => {
    const p = document.createElement('p');
    p.append(...inlineNodes(para.replace(/\s*\n\s*/g, ' ').trim()));
    return p;
  });
}
