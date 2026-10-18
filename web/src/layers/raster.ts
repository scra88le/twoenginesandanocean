// Custom MapLibre layer that draws one packed scalar field.
//
// One quad spans three world copies in mercator space. The fragment shader turns mercator
// coordinates into lat/lon, reads codes from an integer texture with texelFetch (exact, no
// filtering), interpolates bilinearly after decoding, and looks up the colour scale.
// The value -> colour mapping is the same as toT() in scale.ts.
import type { CustomLayerInterface, CustomRenderMethodInput } from 'maplibre-gl';
import type { EncodeRange } from '../codes';
import type { DisplayScale } from '../scale';

const VERTEX = `#version 300 es
uniform mat4 u_matrix;
in vec2 a_pos;
out vec2 v_merc;
void main() {
  v_merc = a_pos;
  gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
}`;

const FRAGMENT = `#version 300 es
precision highp float;
precision highp int;
precision highp usampler2D;
uniform usampler2D u_data;
uniform sampler2D u_lut;
uniform ivec2 u_size;
uniform float u_scale;
uniform float u_offset;
uniform float u_lo;
uniform float u_hi;
uniform float u_centre;
uniform bool u_has_centre;
uniform float u_opacity;
uniform vec4 u_mask_colour;
uniform bool u_hatch_zero;
in vec2 v_merc;
out vec4 frag;
const float PI = 3.141592653589793;

int codeAt(ivec2 p) {
  p.x = ((p.x % u_size.x) + u_size.x) % u_size.x;
  p.y = clamp(p.y, 0, u_size.y - 1);
  uvec4 t = texelFetch(u_data, p, 0);
  return int(t.r) * 256 + int(t.g);
}

float toT(float x) {
  float t = u_has_centre
    ? (x < u_centre ? 0.5 * (x - u_lo) / (u_centre - u_lo) : 0.5 + 0.5 * (x - u_centre) / (u_hi - u_centre))
    : (x - u_lo) / (u_hi - u_lo);
  return clamp(t, 0.0, 1.0);
}

void main() {
  float lon = fract(v_merc.x) * 360.0 - 180.0;
  float lat = degrees(atan(sinh(PI * (1.0 - 2.0 * v_merc.y))));
  vec2 g = vec2((lon + 180.0) / 360.0 * float(u_size.x), (90.0 - lat) / 180.0 * float(u_size.y)) - 0.5;
  int nearest = codeAt(ivec2(floor(g + 0.5)));
  if (nearest == 0) discard;
  if (nearest == 1) { frag = u_mask_colour; return; }
  ivec2 p0 = ivec2(floor(g));
  vec2 f = g - floor(g);
  float sum = 0.0;
  float wsum = 0.0;
  for (int dy = 0; dy < 2; dy++) {
    for (int dx = 0; dx < 2; dx++) {
      int c = codeAt(p0 + ivec2(dx, dy));
      if (c >= 2) {
        float w = (dx == 1 ? f.x : 1.0 - f.x) * (dy == 1 ? f.y : 1.0 - f.y);
        sum += w * (u_offset + u_scale * float(c - 2));
        wsum += w;
      }
    }
  }
  float t = toT(sum / wsum);
  vec3 rgb = texture(u_lut, vec2(t * (255.0 / 256.0) + 0.5 / 256.0, 0.5)).rgb;
  // Cells clamped at exactly zero (the lowest valid code) get light diagonal stripes.
  if (u_hatch_zero && nearest == 2 && mod(gl_FragCoord.x + gl_FragCoord.y, 8.0) < 2.5) {
    rgb = mix(rgb, vec3(1.0), 0.55);
  }
  frag = vec4(rgb * u_opacity, u_opacity);
}`;

export interface RasterData {
  width: number;
  height: number;
  rgb: Uint8Array; // R = high byte, G = low byte, B = 0
  encode: EncodeRange;
  scale: DisplayScale;
  lut: Uint8Array; // 256 x 1 RGBA
  hatchZero: boolean;
}

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? 'shader');
  return s;
}

export class RasterLayer implements CustomLayerInterface {
  readonly type = 'custom' as const;
  readonly renderingMode = '2d' as const;
  opacity = 0.85;
  private program?: WebGLProgram;
  private buffer?: WebGLBuffer;
  private dataTex?: WebGLTexture;
  private lutTex?: WebGLTexture;
  private data?: RasterData;
  private dirty = false;
  private map?: { triggerRepaint(): void };
  private loc: Record<string, WebGLUniformLocation | null> = {};

  constructor(readonly id: string) {}

  setData(data: RasterData): void {
    this.data = data;
    this.dirty = true;
    this.map?.triggerRepaint();
  }

  onAdd(map: { triggerRepaint(): void }, gl: WebGL2RenderingContext): void {
    this.map = map;
    const p = gl.createProgram()!;
    gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? 'link');
    this.program = p;
    for (const n of ['u_matrix', 'u_data', 'u_lut', 'u_size', 'u_scale', 'u_offset', 'u_lo', 'u_hi',
      'u_centre', 'u_has_centre', 'u_opacity', 'u_mask_colour', 'u_hatch_zero']) this.loc[n] = gl.getUniformLocation(p, n);
    // Mercator x in [-1, 2] covers three world copies; y in [0, 1] is +/-85.05 degrees.
    this.buffer = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, 0, 2, 0, -1, 1, 2, 1]), gl.STATIC_DRAW);
    this.dataTex = gl.createTexture()!;
    this.lutTex = gl.createTexture()!;
  }

  private upload(gl: WebGL2RenderingContext, d: RasterData): void {
    // MapLibre resets its cached GL state after custom layers, so changing these is safe.
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.bindTexture(gl.TEXTURE_2D, this.dataTex!);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB8UI, d.width, d.height, 0, gl.RGB_INTEGER, gl.UNSIGNED_BYTE, d.rgb);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.NEAREST], [gl.TEXTURE_MAG_FILTER, gl.NEAREST],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]] as const) {
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    }
    gl.bindTexture(gl.TEXTURE_2D, this.lutTex!);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, d.lut);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]] as const) {
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    }
  }

  render(gl: WebGL2RenderingContext, options: CustomRenderMethodInput): void {
    const d = this.data;
    if (!d || !this.program) return;
    if (this.dirty) {
      this.upload(gl, d);
      this.dirty = false;
    }
    const space = (v: number) => (d.scale.log ? Math.log10(v) : v);
    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.loc.u_matrix!, false, options.defaultProjectionData.mainMatrix);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.dataTex!);
    gl.uniform1i(this.loc.u_data!, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.lutTex!);
    gl.uniform1i(this.loc.u_lut!, 1);
    gl.uniform2i(this.loc.u_size!, d.width, d.height);
    gl.uniform1f(this.loc.u_scale!, d.encode.scale);
    gl.uniform1f(this.loc.u_offset!, d.encode.offset);
    gl.uniform1f(this.loc.u_lo!, space(d.scale.lo));
    gl.uniform1f(this.loc.u_hi!, space(d.scale.hi));
    gl.uniform1i(this.loc.u_has_centre!, d.scale.centre === null ? 0 : 1);
    gl.uniform1f(this.loc.u_centre!, d.scale.centre === null ? 0 : space(d.scale.centre));
    gl.uniform1f(this.loc.u_opacity!, this.opacity);
    gl.uniform1i(this.loc.u_hatch_zero!, d.hatchZero ? 1 : 0);
    gl.uniform4f(this.loc.u_mask_colour!, 0.35 * 0.6, 0.37 * 0.6, 0.4 * 0.6, 0.6); // premultiplied grey
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer!);
    const a = gl.getAttribLocation(this.program, 'a_pos');
    gl.enableVertexAttribArray(a);
    gl.vertexAttribPointer(a, 2, gl.FLOAT, false, 0, 0);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  onRemove(_map: unknown, gl: WebGL2RenderingContext): void {
    if (this.program) gl.deleteProgram(this.program);
    if (this.buffer) gl.deleteBuffer(this.buffer);
    if (this.dataTex) gl.deleteTexture(this.dataTex);
    if (this.lutTex) gl.deleteTexture(this.lutTex);
  }
}
