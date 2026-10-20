// Custom MapLibre layer that animates wind particles (the webgl-wind technique).
//
// Particle state (mercator position now and one step ago, plus seconds left to live) lives in
// a GPU buffer and is advanced each frame with transform feedback, sampling u and v from the
// packed RGBA field with texelFetch and bilinear interpolation after decoding, as raster.ts
// does. Each particle is drawn as a line from its previous to its current position into an
// offscreen trail texture, which fades a little every frame and is drawn over the map.
// When the view moves, the old trail texture is redrawn at its old map position, so trails
// stay attached to the ground while panning and zooming. Particles that leave the view, die
// of age or land on a cell with no data respawn at a random point in the view.
import type { CustomLayerInterface, CustomRenderMethodInput, Map as MapLibreMap } from 'maplibre-gl';
import type { EncodeRange } from '../codes';
import { clipToMercator, invert } from '../mat4';
import { mercatorStep, particleCount } from '../wind';

const UPDATE_VERTEX = `#version 300 es
precision highp float;
precision highp int;
precision highp usampler2D;
uniform usampler2D u_wind;
uniform ivec2 u_size;
uniform float u_scale;
uniform float u_offset;
uniform vec4 u_bounds; // view in mercator: min x, min y, max x, max y
uniform float u_step;  // mercator units per (m/s) this frame
uniform float u_dt;
uniform float u_life;
uniform uint u_seed;
uniform bool u_reset;
in vec4 a_state; // xy = position now, zw = position one step ago
in float a_age;  // seconds left to live
out vec4 v_state;
out float v_age;
const float PI = 3.141592653589793;

uint hash(uint x) { // PCG-style integer hash
  x = x * 747796405u + 2891336453u;
  x = ((x >> ((x >> 28u) + 4u)) ^ x) * 277803737u;
  return (x >> 22u) ^ x;
}
float rand(uint k) { return float(hash(k) & 0xffffffu) / 16777216.0; }

ivec2 wrap(ivec2 p) {
  return ivec2(((p.x % u_size.x) + u_size.x) % u_size.x, clamp(p.y, 0, u_size.y - 1));
}

// Wind (m/s, v northward) at a mercator point; ok = false where no neighbour has data.
vec2 windAt(vec2 merc, out bool ok) {
  float lon = fract(merc.x) * 360.0 - 180.0;
  float lat = degrees(atan(sinh(PI * (1.0 - 2.0 * merc.y))));
  vec2 g = vec2((lon + 180.0) / 360.0 * float(u_size.x), (90.0 - lat) / 180.0 * float(u_size.y)) - 0.5;
  ivec2 p0 = ivec2(floor(g));
  vec2 f = g - floor(g);
  vec2 sum = vec2(0.0);
  float wsum = 0.0;
  for (int dy = 0; dy < 2; dy++) {
    for (int dx = 0; dx < 2; dx++) {
      uvec4 t = texelFetch(u_wind, wrap(p0 + ivec2(dx, dy)), 0);
      int cu = int(t.r) * 256 + int(t.g);
      int cv = int(t.b) * 256 + int(t.a);
      if (cu >= 2 && cv >= 2) {
        float w = (dx == 1 ? f.x : 1.0 - f.x) * (dy == 1 ? f.y : 1.0 - f.y);
        sum += w * (u_offset + u_scale * vec2(float(cu - 2), float(cv - 2)));
        wsum += w;
      }
    }
  }
  ok = wsum > 0.0;
  return ok ? sum / wsum : vec2(0.0);
}

void main() {
  uint id = uint(gl_VertexID) * 3u;
  vec2 p = a_state.xy;
  float age = a_age - u_dt;
  bool outside = p.x < u_bounds.x || p.y < u_bounds.y || p.x > u_bounds.z || p.y > u_bounds.w;
  if (u_reset || age <= 0.0 || outside) {
    vec2 q = mix(u_bounds.xy, u_bounds.zw, vec2(rand(id ^ u_seed), rand((id + 1u) ^ u_seed)));
    v_state = vec4(q, q);
    // A random first life spreads the respawns out, so they don't pulse.
    v_age = u_life * (u_reset ? rand((id + 2u) ^ u_seed) : 0.5 + 0.5 * rand((id + 2u) ^ u_seed));
    return;
  }
  bool ok;
  vec2 w = windAt(p, ok);
  v_state = vec4(p + vec2(w.x, -w.y) * u_step, p); // mercator y grows southwards
  v_age = ok ? age : 0.0;
}`;

const UPDATE_FRAGMENT = `#version 300 es
precision mediump float;
out vec4 frag;
void main() { frag = vec4(0.0); }`;

const LINE_VERTEX = `#version 300 es
uniform mat4 u_matrix;
in vec4 a_state;
void main() {
  vec2 p = gl_VertexID == 0 ? a_state.zw : a_state.xy;
  gl_Position = u_matrix * vec4(p, 0.0, 1.0);
}`;

const LINE_FRAGMENT = `#version 300 es
precision mediump float;
uniform float u_alpha;
out vec4 frag;
void main() { frag = vec4(u_alpha); } // premultiplied white`;

// Draws a texture onto a quad: the old trails at their old map position, or the trails on screen.
const QUAD_VERTEX = `#version 300 es
uniform mat4 u_matrix;
in vec2 a_pos;
in vec2 a_uv;
out vec2 v_uv;
void main() {
  v_uv = a_uv;
  gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
}`;

const QUAD_FRAGMENT = `#version 300 es
precision highp float;
uniform sampler2D u_tex;
uniform float u_fade;
in vec2 v_uv;
out vec4 frag;
void main() {
  // floor() so faint trails always lose at least one level and fade out completely.
  frag = floor(texture(u_tex, v_uv) * 255.0 * u_fade) / 255.0;
}`;

export interface WindField {
  width: number;
  height: number;
  rgba: Uint8Array; // u in R+G, v in B+A
  encode: EncodeRange; // shared by u and v
  speedHi: number; // top of the level's colour range, m/s
}

const STATE_FLOATS = 5; // vec4 state + float age
const LIFE_S = 4;
const FADE_PER_60TH = 0.96;
const LINE_ALPHA = 0.9;
const IDENTITY = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? 'shader');
  return s;
}

function link(gl: WebGL2RenderingContext, vs: string, fs: string, feedback?: string[]): WebGLProgram {
  const p = gl.createProgram()!;
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
  if (feedback) gl.transformFeedbackVaryings(p, feedback, gl.INTERLEAVED_ATTRIBS);
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? 'link');
  return p;
}

interface Trail {
  tex: WebGLTexture;
  fbo: WebGLFramebuffer;
}

export class ParticleLayer implements CustomLayerInterface {
  readonly type = 'custom' as const;
  readonly renderingMode = '2d' as const;
  private map?: MapLibreMap;
  private wind?: WindField;
  private windDirty = false;
  private update?: WebGLProgram;
  private lines?: WebGLProgram;
  private quad?: WebGLProgram;
  private windTex?: WebGLTexture;
  private states: WebGLBuffer[] = [];
  private updateVaos: WebGLVertexArrayObject[] = [];
  private lineVaos: WebGLVertexArrayObject[] = [];
  private feedback?: WebGLTransformFeedback;
  private quadBuffer?: WebGLBuffer;
  private quadVao?: WebGLVertexArrayObject;
  private trails: Trail[] = [];
  private trailSize: [number, number] = [0, 0];
  private count = 0;
  private current = 0; // which state buffer holds the latest positions
  private reset = true;
  private lastTime = 0;
  private frame = 0;
  private corners: number[] | null = null; // mercator corners of the view the trails were drawn in
  private loc: Record<string, WebGLUniformLocation | null> = {};
  private stateRequests: ((state: Float32Array) => void)[] = [];

  constructor(readonly id: string) {}

  /**
   * For tests and debugging: the particle state after the next update, as [x, y, prev x,
   * prev y, seconds left] per particle in mercator units. Read inside prerender, where
   * MapLibre expects GL state to change.
   */
  readState(): Promise<Float32Array> {
    return new Promise((resolve) => {
      this.stateRequests.push(resolve);
      this.map?.triggerRepaint();
    });
  }

  /** Show wind from this field, or hide the particles with null. */
  setWind(wind: WindField | null): void {
    const was = this.wind;
    this.wind = wind ?? undefined;
    this.windDirty = !!wind;
    if (!wind || !was) this.reset = true;
    this.map?.triggerRepaint();
  }

  get active(): boolean {
    return !!this.wind;
  }

  /** How many particles are being simulated (halved on phones, see wind.particleCount). */
  get particleTotal(): number {
    return this.count;
  }

  onAdd(map: MapLibreMap, gl: WebGL2RenderingContext): void {
    this.map = map;
    this.update = link(gl, UPDATE_VERTEX, UPDATE_FRAGMENT, ['v_state', 'v_age']);
    this.lines = link(gl, LINE_VERTEX, LINE_FRAGMENT);
    this.quad = link(gl, QUAD_VERTEX, QUAD_FRAGMENT);
    const find = (prefix: string, p: WebGLProgram, names: string[]) => {
      for (const n of names) this.loc[`${prefix}.${n}`] = gl.getUniformLocation(p, n);
    };
    find('up', this.update, ['u_wind', 'u_size', 'u_scale', 'u_offset', 'u_bounds', 'u_step', 'u_dt', 'u_life', 'u_seed', 'u_reset']);
    find('ln', this.lines, ['u_matrix', 'u_alpha']);
    find('qd', this.quad, ['u_matrix', 'u_tex', 'u_fade']);
    this.windTex = gl.createTexture()!;
    this.feedback = gl.createTransformFeedback()!;
    this.quadBuffer = gl.createBuffer()!;
    this.quadVao = gl.createVertexArray()!;
    gl.bindVertexArray(this.quadVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuffer);
    const qp = gl.getAttribLocation(this.quad, 'a_pos');
    const qu = gl.getAttribLocation(this.quad, 'a_uv');
    gl.enableVertexAttribArray(qp);
    gl.vertexAttribPointer(qp, 2, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(qu);
    gl.vertexAttribPointer(qu, 2, gl.FLOAT, false, 16, 8);
    gl.bindVertexArray(null);
    const canvas = map.getCanvas();
    this.allocate(gl, particleCount(canvas.clientWidth, canvas.clientHeight));
  }

  private allocate(gl: WebGL2RenderingContext, count: number): void {
    for (const b of this.states) gl.deleteBuffer(b);
    for (const v of [...this.updateVaos, ...this.lineVaos]) gl.deleteVertexArray(v);
    this.count = count;
    this.states = [gl.createBuffer()!, gl.createBuffer()!];
    this.updateVaos = [];
    this.lineVaos = [];
    const bytes = count * STATE_FLOATS * 4;
    for (const b of this.states) {
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, bytes, gl.DYNAMIC_COPY);
    }
    const ua = gl.getAttribLocation(this.update!, 'a_state');
    const ug = gl.getAttribLocation(this.update!, 'a_age');
    const la = gl.getAttribLocation(this.lines!, 'a_state');
    for (const b of this.states) {
      const uv = gl.createVertexArray()!;
      gl.bindVertexArray(uv);
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.enableVertexAttribArray(ua);
      gl.vertexAttribPointer(ua, 4, gl.FLOAT, false, STATE_FLOATS * 4, 0);
      gl.enableVertexAttribArray(ug);
      gl.vertexAttribPointer(ug, 1, gl.FLOAT, false, STATE_FLOATS * 4, 16);
      this.updateVaos.push(uv);
      const lv = gl.createVertexArray()!;
      gl.bindVertexArray(lv);
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.enableVertexAttribArray(la);
      gl.vertexAttribPointer(la, 4, gl.FLOAT, false, STATE_FLOATS * 4, 0);
      gl.vertexAttribDivisor(la, 1); // one particle per instance, two vertices per line
      this.lineVaos.push(lv);
    }
    gl.bindVertexArray(null);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    this.reset = true;
  }

  private ensureTrails(gl: WebGL2RenderingContext, w: number, h: number): void {
    if (this.trailSize[0] === w && this.trailSize[1] === h) return;
    for (const t of this.trails) {
      gl.deleteTexture(t.tex);
      gl.deleteFramebuffer(t.fbo);
    }
    this.trails = [0, 1].map(() => {
      const tex = gl.createTexture()!;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
        [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]] as const) {
        gl.texParameteri(gl.TEXTURE_2D, k, v);
      }
      const fbo = gl.createFramebuffer()!;
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      return { tex, fbo };
    });
    this.trailSize = [w, h];
    this.corners = null;
  }

  private uploadWind(gl: WebGL2RenderingContext, w: WindField): void {
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.bindTexture(gl.TEXTURE_2D, this.windTex!);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8UI, w.width, w.height, 0, gl.RGBA_INTEGER, gl.UNSIGNED_BYTE, w.rgba);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.NEAREST], [gl.TEXTURE_MAG_FILTER, gl.NEAREST],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]] as const) {
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    }
  }

  /** Mercator corners of the view, in the order bottom-left, bottom-right, top-left, top-right. */
  private viewCorners(matrix: ArrayLike<number>): number[] | null {
    const inv = invert(matrix);
    return inv && [[-1, -1], [1, -1], [-1, 1], [1, 1]].flatMap(([x, y]) => clipToMercator(inv, x!, y!));
  }

  prerender(gl: WebGL2RenderingContext, options: CustomRenderMethodInput): void {
    const map = this.map;
    const wind = this.wind;
    if (!map || !wind || !this.update) return;
    if (this.windDirty) {
      this.uploadWind(gl, wind);
      this.windDirty = false;
    }
    const canvas = map.getCanvas();
    const wanted = particleCount(canvas.clientWidth, canvas.clientHeight);
    if (Math.abs(wanted - this.count) > this.count / 4) this.allocate(gl, wanted);
    this.ensureTrails(gl, gl.drawingBufferWidth, gl.drawingBufferHeight);

    const matrix = options.defaultProjectionData.mainMatrix;
    const corners = this.viewCorners(matrix);
    if (!corners) return;
    const now = performance.now();
    const dt = this.lastTime ? Math.min((now - this.lastTime) / 1000, 0.05) : 1 / 60;
    this.lastTime = now;
    this.frame++;
    const xs = [corners[0]!, corners[2]!, corners[4]!, corners[6]!];
    const ys = [corners[1]!, corners[3]!, corners[5]!, corners[7]!];
    const bounds = [Math.min(...xs), Math.max(0, Math.min(...ys)), Math.max(...xs), Math.min(1, Math.max(...ys))];

    // 1. Advance the particles.
    gl.useProgram(this.update);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.windTex!);
    gl.uniform1i(this.loc['up.u_wind']!, 0);
    gl.uniform2i(this.loc['up.u_size']!, wind.width, wind.height);
    gl.uniform1f(this.loc['up.u_scale']!, wind.encode.scale);
    gl.uniform1f(this.loc['up.u_offset']!, wind.encode.offset);
    gl.uniform4f(this.loc['up.u_bounds']!, bounds[0]!, bounds[1]!, bounds[2]!, bounds[3]!);
    gl.uniform1f(this.loc['up.u_step']!, mercatorStep(wind.speedHi, map.getZoom(), dt));
    gl.uniform1f(this.loc['up.u_dt']!, dt);
    gl.uniform1f(this.loc['up.u_life']!, LIFE_S);
    gl.uniform1ui(this.loc['up.u_seed']!, (this.frame * 2654435761) >>> 0);
    gl.uniform1i(this.loc['up.u_reset']!, this.reset ? 1 : 0);
    const next = 1 - this.current;
    gl.bindVertexArray(this.updateVaos[this.current]!);
    gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, this.feedback!);
    gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, this.states[next]!);
    gl.enable(gl.RASTERIZER_DISCARD);
    gl.beginTransformFeedback(gl.POINTS);
    gl.drawArrays(gl.POINTS, 0, this.count);
    gl.endTransformFeedback();
    gl.disable(gl.RASTERIZER_DISCARD);
    gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, null);
    gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);
    this.current = next;
    if (this.stateRequests.length) {
      const state = new Float32Array(this.count * STATE_FLOATS);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.states[next]!);
      gl.getBufferSubData(gl.ARRAY_BUFFER, 0, state);
      gl.bindBuffer(gl.ARRAY_BUFFER, null);
      for (const resolve of this.stateRequests.splice(0)) resolve(state);
    }

    // 2. Fade the old trails into the other texture, at the map position they were drawn at.
    const [src, dst] = this.trails as [Trail, Trail];
    gl.bindFramebuffer(gl.FRAMEBUFFER, dst.fbo);
    gl.viewport(0, 0, this.trailSize[0], this.trailSize[1]);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.STENCIL_TEST);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (this.corners && !this.reset) {
      const c = this.corners;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuffer!);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
        c[0]!, c[1]!, 0, 0, c[2]!, c[3]!, 1, 0, c[4]!, c[5]!, 0, 1, c[6]!, c[7]!, 1, 1,
      ]), gl.DYNAMIC_DRAW);
      gl.useProgram(this.quad!);
      gl.uniformMatrix4fv(this.loc['qd.u_matrix']!, false, matrix);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, src.tex);
      gl.uniform1i(this.loc['qd.u_tex']!, 0);
      gl.uniform1f(this.loc['qd.u_fade']!, FADE_PER_60TH ** (dt * 60));
      gl.disable(gl.BLEND);
      gl.bindVertexArray(this.quadVao!);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }

    // 3. Draw this frame's steps on top.
    gl.useProgram(this.lines!);
    gl.uniformMatrix4fv(this.loc['ln.u_matrix']!, false, matrix);
    gl.uniform1f(this.loc['ln.u_alpha']!, LINE_ALPHA);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.bindVertexArray(this.lineVaos[this.current]!);
    gl.drawArraysInstanced(gl.LINES, 0, 2, this.count);
    gl.bindVertexArray(null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);

    this.trails = [dst, src];
    this.corners = corners;
    this.reset = false;
  }

  render(gl: WebGL2RenderingContext): void {
    if (!this.wind || !this.quad || this.trails.length < 2 || !this.corners) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuffer!);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 0, 0, 1, -1, 1, 0, -1, 1, 0, 1, 1, 1, 1, 1]), gl.DYNAMIC_DRAW);
    gl.useProgram(this.quad);
    gl.uniformMatrix4fv(this.loc['qd.u_matrix']!, false, IDENTITY);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.trails[0]!.tex);
    gl.uniform1i(this.loc['qd.u_tex']!, 0);
    gl.uniform1f(this.loc['qd.u_fade']!, 1);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.bindVertexArray(this.quadVao!);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);
    this.map?.triggerRepaint(); // keep animating
  }

  onRemove(_map: unknown, gl: WebGL2RenderingContext): void {
    for (const p of [this.update, this.lines, this.quad]) if (p) gl.deleteProgram(p);
    for (const b of [...this.states, this.quadBuffer]) if (b) gl.deleteBuffer(b);
    for (const v of [...this.updateVaos, ...this.lineVaos, this.quadVao]) if (v) gl.deleteVertexArray(v);
    for (const t of this.trails) {
      gl.deleteTexture(t.tex);
      gl.deleteFramebuffer(t.fbo);
    }
    if (this.windTex) gl.deleteTexture(this.windTex);
    if (this.feedback) gl.deleteTransformFeedback(this.feedback);
  }
}
