// Transport arrows: the divergent part of the energy flux (flux_e), drawn as arrows on a
// regular screen grid. Each arrow points along the flux and its length is proportional to
// the flux, up to a reference (the day's 98th percentile) at which it fills its grid cell.
//
// Positions and directions are worked out on the CPU every frame (a few hundred samples) from
// the packed u, v codes, which keeps the geometry testable; the GPU only draws them, as
// instanced triangles: a dark halo pass, then a white pass.
import type { CustomLayerInterface, CustomRenderMethodInput, Map as MapLibreMap } from 'maplibre-gl';
import { FIRST_VALID, decodeValue, type EncodeRange } from '../codes';
import type { Grid } from '../manifest';
import { clipToMercator, invert } from '../mat4';

export interface ArrowField {
  u: Uint16Array; // codes, eastward
  v: Uint16Array; // codes, northward
  encode: EncodeRange; // shared by u and v
  grid: Grid;
  reference: number; // flux (layer units) drawn at full length
}

const PI = Math.PI;
const MIN_LENGTH_PX = 5;

/** Screen spacing of the arrow grid in CSS px: wider on phones. */
export const arrowSpacing = (width: number) => (width < 700 ? 52 : 44);

/** The flux that fills a grid cell: the 98th percentile of the magnitude over valid cells. */
export function arrowReference(u: Uint16Array, v: Uint16Array, enc: EncodeRange): number {
  const mags: number[] = [];
  for (let k = 0; k < u.length; k++) {
    if (u[k]! >= FIRST_VALID && v[k]! >= FIRST_VALID) {
      mags.push(Math.hypot(decodeValue(u[k]!, enc), decodeValue(v[k]!, enc)));
    }
  }
  if (!mags.length) return 1;
  mags.sort((a, b) => a - b);
  return mags[Math.floor(0.98 * (mags.length - 1))] || 1;
}

/** Bilinear (u, v) at a point from the four surrounding cells, skipping invalid ones. */
export function sampleUV(f: ArrowField, lng: number, lat: number): [number, number] | null {
  const g = f.grid;
  const gx = (lng - g.lon0) / g.step;
  const gy = (g.lat0 - lat) / g.step;
  const i0 = Math.floor(gx);
  const j0 = Math.floor(gy);
  const fx = gx - i0;
  const fy = gy - j0;
  let su = 0;
  let sv = 0;
  let sw = 0;
  for (let dj = 0; dj < 2; dj++) {
    for (let di = 0; di < 2; di++) {
      const j = j0 + dj;
      if (j < 0 || j >= g.nlat) continue;
      const i = (((i0 + di) % g.nlon) + g.nlon) % g.nlon;
      const k = j * g.nlon + i;
      const cu = f.u[k]!;
      const cv = f.v[k]!;
      if (cu < FIRST_VALID || cv < FIRST_VALID) continue;
      const w = (di ? fx : 1 - fx) * (dj ? fy : 1 - fy);
      su += w * decodeValue(cu, f.encode);
      sv += w * decodeValue(cv, f.encode);
      sw += w;
    }
  }
  return sw > 0 ? [su / sw, sv / sw] : null;
}

/**
 * One arrow per screen grid point: [clip x, clip y, dx, dy] with the direction and length in
 * CSS px (x right, y up). `inverse` is the inverse of the mercator -> clip matrix.
 */
export function arrowInstances(
  inverse: ArrayLike<number>, width: number, height: number, spacing: number, f: ArrowField,
): Float32Array {
  const nx = Math.floor(width / spacing);
  const ny = Math.floor(height / spacing);
  const padX = (width - nx * spacing) / 2;
  const padY = (height - ny * spacing) / 2;
  const maxLen = spacing * 0.9;
  const out: number[] = [];
  for (let gy = 0; gy < ny; gy++) {
    for (let gx = 0; gx < nx; gx++) {
      const px = padX + (gx + 0.5) * spacing;
      const py = padY + (gy + 0.5) * spacing;
      const cx = (px / width) * 2 - 1;
      const cy = 1 - (py / height) * 2;
      const [mx, my] = clipToMercator(inverse, cx, cy);
      if (my <= 0 || my >= 1) continue; // above or below the world
      const lng = (mx - Math.floor(mx)) * 360 - 180;
      const lat = (Math.atan(Math.sinh(PI * (1 - 2 * my))) * 180) / PI;
      const uv = sampleUV(f, lng, lat);
      if (!uv) continue;
      const mag = Math.hypot(uv[0], uv[1]);
      const len = maxLen * Math.min(1, mag / f.reference);
      if (len < MIN_LENGTH_PX) continue;
      out.push(cx, cy, (uv[0] / mag) * len, (uv[1] / mag) * len);
    }
  }
  return Float32Array.from(out);
}

const VERTEX = `#version 300 es
in vec4 a_inst; // clip centre (xy), direction and length in px (zw)
uniform vec2 u_clip_per_px;
uniform float u_grow; // px added all round, for the halo
void main() {
  float len = length(a_inst.zw);
  vec2 d = a_inst.zw / len;
  vec2 n = vec2(-d.y, d.x);
  float w = 1.1 + u_grow;
  float h = min(7.0, len * 0.5);
  float hw = 3.4 + u_grow;
  float a = -len * 0.5 - u_grow;
  float b = len * 0.5 - h;
  float tip = len * 0.5 + u_grow * 1.5;
  vec2 shape[9] = vec2[9](
    vec2(a, -w), vec2(b, -w), vec2(a, w),
    vec2(a, w), vec2(b, -w), vec2(b, w),
    vec2(b - u_grow, -hw), vec2(tip, 0.0), vec2(b - u_grow, hw)
  );
  vec2 q = shape[gl_VertexID];
  gl_Position = vec4(a_inst.xy + (d * q.x + n * q.y) * u_clip_per_px, 0.0, 1.0);
}`;

const FRAGMENT = `#version 300 es
precision mediump float;
uniform vec4 u_colour; // premultiplied
out vec4 frag;
void main() { frag = u_colour; }`;

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? 'shader');
  return s;
}

export class ArrowLayer implements CustomLayerInterface {
  readonly type = 'custom' as const;
  readonly renderingMode = '2d' as const;
  /** Arrows drawn in the last frame, and their data: for tests and debugging. */
  lastInstances: Float32Array = new Float32Array(0);
  private field: ArrowField | null = null;
  private map?: MapLibreMap;
  private program?: WebGLProgram;
  private buffer?: WebGLBuffer;
  private vao?: WebGLVertexArrayObject;
  private loc: Record<string, WebGLUniformLocation | null> = {};

  constructor(readonly id: string) {}

  /** Show arrows for this field, or hide them with null. */
  setField(field: ArrowField | null): void {
    this.field = field;
    if (!field) this.lastInstances = new Float32Array(0);
    this.map?.triggerRepaint();
  }

  get active(): boolean {
    return !!this.field;
  }

  onAdd(map: MapLibreMap, gl: WebGL2RenderingContext): void {
    this.map = map;
    const p = gl.createProgram()!;
    gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? 'link');
    this.program = p;
    for (const n of ['u_clip_per_px', 'u_grow', 'u_colour']) this.loc[n] = gl.getUniformLocation(p, n);
    this.buffer = gl.createBuffer()!;
    this.vao = gl.createVertexArray()!;
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    const a = gl.getAttribLocation(p, 'a_inst');
    gl.enableVertexAttribArray(a);
    gl.vertexAttribPointer(a, 4, gl.FLOAT, false, 16, 0);
    gl.vertexAttribDivisor(a, 1);
    gl.bindVertexArray(null);
  }

  render(gl: WebGL2RenderingContext, options: CustomRenderMethodInput): void {
    const f = this.field;
    const map = this.map;
    if (!f || !map || !this.program) return;
    const canvas = map.getCanvas();
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const inv = invert(options.defaultProjectionData.mainMatrix);
    if (!inv || !w || !h) return;
    const inst = arrowInstances(inv, w, h, arrowSpacing(w), f);
    this.lastInstances = inst;
    if (!inst.length) return;
    gl.useProgram(this.program);
    gl.bindVertexArray(this.vao!);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer!);
    gl.bufferData(gl.ARRAY_BUFFER, inst, gl.DYNAMIC_DRAW);
    gl.uniform2f(this.loc.u_clip_per_px!, 2 / w, 2 / h);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    const count = inst.length / 4;
    gl.uniform1f(this.loc.u_grow!, 1.6); // dark halo, so arrows read on any colour
    gl.uniform4f(this.loc.u_colour!, 0, 0, 0, 0.6);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 9, count);
    gl.uniform1f(this.loc.u_grow!, 0);
    gl.uniform4f(this.loc.u_colour!, 0.97, 0.97, 0.97, 0.97);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 9, count);
    gl.bindVertexArray(null);
  }

  onRemove(_map: unknown, gl: WebGL2RenderingContext): void {
    if (this.program) gl.deleteProgram(this.program);
    if (this.buffer) gl.deleteBuffer(this.buffer);
    if (this.vao) gl.deleteVertexArray(this.vao);
  }
}
