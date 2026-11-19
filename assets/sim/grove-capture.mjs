// SSCMA camera samples use a CR-prefixed JSON packet followed by LF.
const MAX_PACKET = 1_000_000;
export const MAX_FRAMES = 60;
export const FRAME_LIMIT = 768;
export const CAPTURE_FORMAT = 'duck-lab-camera-v1';

export function jpegBytes(image) {
  if (typeof image !== 'string' || image.length > MAX_PACKET || !image.startsWith('/9j/')) {
    throw new Error('Expected a base64 JPEG camera frame.');
  }
  const raw = atob(image);
  let end = raw.length;
  while (end && raw.charCodeAt(end-1) === 0) end--;
  if (end < 4 || raw.charCodeAt(end-2) !== 255 || raw.charCodeAt(end-1) !== 217) {
    throw new Error('Incomplete JPEG camera frame.');
  }
  return Uint8Array.from(raw.slice(0,end), byte => byte.charCodeAt(0));
}

export class SamplePackets {
  buffer = '';

  feed(text) {
    this.buffer += text;
    const samples = [];
    for (;;) {
      const start = this.buffer.indexOf('\r{');
      if (start < 0) {
        this.buffer = this.buffer.endsWith('\r') ? '\r' : '';
        break;
      }
      const end = this.buffer.indexOf('}\n', start+2);
      if (end < 0) {
        this.buffer = this.buffer.slice(start);
        if (this.buffer.length > MAX_PACKET + 2048) throw new Error('Grove camera packet exceeded the size limit.');
        break;
      }
      const raw = this.buffer.slice(start+1,end+1);
      this.buffer = this.buffer.slice(end+2);
      if (raw.length > MAX_PACKET + 2048) throw new Error('Grove camera packet exceeded the size limit.');
      let packet;
      try { packet = JSON.parse(raw); }
      catch { continue; }
      if (packet?.name !== 'SAMPLE' || ![0,1].includes(packet.type)) continue;
      if (packet.code !== 0) throw new Error(`Grove rejected the camera sample (SSCMA code ${packet.code}).`);
      if (packet.type === 1) samples.push(packet.data?.image);
    }
    return samples;
  }
}

export class GroveCamera {
  constructor(port) {
    this.port = port;
  }

  async open() {
    await this.port.open({baudRate:921600, bufferSize:65536});
    this.reader = this.port.readable.getReader();
    this.writer = this.port.writable.getWriter();
    this.reading = this.read();
  }

  async read() {
    const packets = new SamplePackets(), decoder = new TextDecoder();
    try {
      while (true) {
        const {value, done} = await this.reader.read();
        if (done) throw new Error('Grove camera disconnected.');
        for (const image of packets.feed(decoder.decode(value,{stream:true}))) {
          if (!this.pending) continue;
          jpegBytes(image);
          this.pending.resolve(image);
          this.pending = null;
        }
      }
    } catch (error) {
      this.failure = error;
      this.pending?.reject(error);
      this.pending = null;
    }
  }

  async sample(timeoutMs = 6000) {
    if (this.failure) throw this.failure;
    if (this.pending) throw new Error('A Grove capture is already running.');
    let timeout;
    const result = new Promise((resolve, reject) => {
      this.pending = {resolve, reject};
      timeout = setTimeout(() => reject(new Error('No image received. Check the camera ribbon and SSCMA firmware.')), timeoutMs);
    });
    try {
      // Issue one sensor sample. The inference comparison runs in Duck Lab.
      const write = this.writer.write(new TextEncoder().encode('AT+SAMPLE=1\r\n'));
      const [image] = await Promise.all([result, write]);
      return image;
    } catch (error) {
      this.failure = error;
      throw error;
    } finally {
      clearTimeout(timeout);
      this.pending = null;
    }
  }

  async close() {
    this.pending?.reject(new Error('Capture stopped.'));
    this.pending = null;
    if (this.reader) {
      await this.reader.cancel().catch(() => {});
      await this.reading;
      this.reader.releaseLock();
    }
    if (this.writer) {
      await this.writer.abort().catch(() => {});
      this.writer.releaseLock();
    }
    if (this.port.readable || this.port.writable) await this.port.close();
  }
}

export function parseRecording(recording) {
  if (recording?.format !== CAPTURE_FORMAT || !Array.isArray(recording.frames)
      || !recording.frames.length || recording.frames.length > MAX_FRAMES) {
    throw new Error('Choose a Duck Lab camera recording with 1–60 frames.');
  }
  let last = -1;
  for (const frame of recording.frames) {
    if (!(Number.isFinite(frame?.t) && frame.t >= 0 && frame.t > last)
        || !['unknown','present','absent'].includes(frame.truth)) {
      throw new Error('The recording contains invalid frame timing or labels.');
    }
    jpegBytes(frame.jpeg);
    if (frame.box !== undefined && (frame.truth !== 'present' || !Array.isArray(frame.box)
        || frame.box.length !== 4 || !frame.box.every(n => Number.isFinite(n) && n >= 0 && n <= 1)
        || frame.box[0] >= frame.box[2] || frame.box[1] >= frame.box[3])) {
      throw new Error('The recording contains an invalid dock annotation.');
    }
    last = frame.t;
  }
  return recording.frames;
}
