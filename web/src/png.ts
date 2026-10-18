// Minimal PNG decoder for the pipeline's own files: 8-bit RGB or RGBA, not interlaced.
// Decoding in JS gives the exact bytes, with no premultiplied alpha or colour management,
// which would corrupt packed data (the v component lives in the alpha channel).

export interface DecodedPng {
  width: number;
  height: number;
  channels: 3 | 4;
  data: Uint8Array; // row-major, `channels` bytes per pixel
}

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];

async function inflate(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream('deflate'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

export async function decodePng(input: ArrayBuffer | Uint8Array): Promise<DecodedPng> {
  const buf = input instanceof Uint8Array ? input : new Uint8Array(input);
  if (buf.length < 8 || SIGNATURE.some((b, k) => buf[k] !== b)) throw new Error('not a PNG file');
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  let width = 0;
  let height = 0;
  let channels: 3 | 4 = 3;
  const idat: Uint8Array[] = [];
  for (let pos = 8; pos + 8 <= buf.length; ) {
    const length = view.getUint32(pos);
    const type = String.fromCharCode(...buf.subarray(pos + 4, pos + 8));
    const body = buf.subarray(pos + 8, pos + 8 + length);
    if (type === 'IHDR') {
      width = view.getUint32(pos + 8);
      height = view.getUint32(pos + 12);
      const [depth, colourType, , , interlace] = body.subarray(8, 13);
      if (depth !== 8 || (colourType !== 2 && colourType !== 6) || interlace !== 0) {
        throw new Error(`unsupported PNG: depth ${depth}, colour type ${colourType}, interlace ${interlace}`);
      }
      channels = colourType === 2 ? 3 : 4;
    } else if (type === 'IDAT') {
      idat.push(body);
    } else if (type === 'IEND') {
      break;
    }
    pos += 12 + length;
  }
  const joined = new Uint8Array(idat.reduce((n, c) => n + c.length, 0));
  idat.reduce((off, c) => (joined.set(c, off), off + c.length), 0);
  const raw = await inflate(joined);

  const stride = width * channels;
  if (raw.length < height * (stride + 1)) throw new Error('truncated PNG data');
  const data = new Uint8Array(height * stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const src = y * (stride + 1) + 1;
    const out = y * stride;
    const prev = out - stride;
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? data[out + x - channels]! : 0;
      const b = y > 0 ? data[prev + x]! : 0;
      const c = x >= channels && y > 0 ? data[prev + x - channels]! : 0;
      const r = raw[src + x]!;
      let v: number;
      switch (filter) {
        case 0: v = r; break;
        case 1: v = r + a; break;
        case 2: v = r + b; break;
        case 3: v = r + ((a + b) >> 1); break;
        case 4: v = r + paeth(a, b, c); break;
        default: throw new Error(`bad PNG filter ${filter}`);
      }
      data[out + x] = v & 0xff;
    }
  }
  return { width, height, channels, data };
}
