import {Quaternion} from 'three';

const $ = id => document.getElementById(id);
const lerp = (a, b, t) => a + (b - a) * t;
const number = (value, digits, suffix) => Number.isFinite(value) ? value.toFixed(digits) + suffix : '—';

export class StuntReplay {
  constructor() {
    this.frames = [];
    this.firstRotation = new Quaternion();
    this.secondRotation = new Quaternion();
    $('replay-play').addEventListener('click', () => {
      if (!this.clip) return;
      if (!this.active || this.time >= this.clip.end) this.start();
      else this.playing = !this.playing;
      this.refresh();
    });
    $('replay-live').addEventListener('click', () => this.live());
    $('replay-seek').addEventListener('input', event => {
      this.active = true;
      this.playing = false;
      this.time = Number(event.target.value);
      this.refresh();
    });
  }

  observe(packet, board) {
    if (!packet?.run_key || packet.arena || !Number.isFinite(packet.time_s) || !packet.root) return;
    if (this.runKey !== packet.run_key) {
      this.live();
      this.runKey = packet.run_key;
      this.frames = [];
    }
    if (packet.time_s > (this.frames.at(-1)?.time_s ?? -1)) {
      this.frames.push({...packet, cpu:board?.cpu?.load_percent, gpu:board?.gpu?.load_percent});
    }
    const resumed = packet.recovery?.resumed_at_s;
    if (packet.state !== 'complete' || this.clip?.key === this.runKey || !packet.push?.fell || !Number.isFinite(resumed)) return;
    const frames = this.frames.filter(frame => frame.time_s >= packet.push.time_s - 1 && frame.time_s <= resumed + 1.2);
    if (frames.length < 5 || frames[0].time_s > packet.push.time_s || frames.at(-1).time_s < resumed) return;
    this.clip = {key:this.runKey, frames, start:frames[0].time_s, end:frames.at(-1).time_s,
      bash:packet.push.time_s, getup:packet.recovery.getup_at_s, resumed};
    const seek = $('replay-seek');
    seek.min = this.clip.start;
    seek.max = this.clip.end;
    const max = Math.max(25, ...frames.map(frame => frame.slot_p95_ms || 0));
    const y = ms => 48 - 44 * ms / max;
    $('replay-budget').setAttribute('d', `M0 ${y(20)}H290`);
    $('replay-work').setAttribute('d', frames.filter(f => Number.isFinite(f.slot_p95_ms)).map((f, i) =>
      `${i ? 'L' : 'M'}${this.x(f.time_s)} ${y(f.slot_p95_ms)}`).join(' '));
    $('replay-events').setAttribute('d', [this.clip.bash, this.clip.getup, resumed].map(t => `M${this.x(t)} 4V48`).join(' '));
    $('replay-card').hidden = false;
    this.start();
  }

  x(time) {
    return 290 * (time - this.clip.start) / (this.clip.end - this.clip.start);
  }

  start() {
    this.active = this.playing = true;
    this.time = this.clip.start;
    this.refresh();
  }

  live() {
    this.active = this.playing = false;
    this.refresh();
  }

  refresh() {
    $('replay-play').textContent = this.playing ? 'Pause replay' : this.active ? 'Play replay' : 'Replay Bash';
    $('replay-live').disabled = !this.active;
  }

  packet(dt) {
    if (!this.active || !this.clip) return null;
    if (this.playing) {
      this.time = Math.min(this.clip.end, this.time + dt * .45);
      if (this.time >= this.clip.end) {
        this.live();
        return null;
      }
    }
    const {frames, bash, getup, resumed} = this.clip;
    const i = Math.max(1, frames.findIndex(frame => frame.time_s >= this.time));
    const a = frames[i - 1], b = frames[i];
    const mix = Math.min(1, Math.max(0, (this.time - a.time_s) / (b.time_s - a.time_s)));
    const nearest = mix < .5 ? a : b;
    const phase = this.time < bash ? 'Walking' : this.time < getup ? 'Bash and fall'
      : this.time < resumed ? 'Get-up policy' : 'Walking again';
    $('replay-seek').value = this.time;
    $('replay-phase').textContent = `${this.time.toFixed(2)} s · ${phase}`;
    $('replay-metrics').textContent = `CPU ${number(nearest.cpu, 0, '%')} · Adreno ${number(nearest.gpu, 1, '%')} · slot p95 ${number(nearest.slot_p95_ms, 2, ' ms')}`;
    $('replay-cursor').setAttribute('d', `M${this.x(this.time)} 2V50`);
    this.firstRotation.set(a.root[4], a.root[5], a.root[6], a.root[3]);
    this.secondRotation.set(b.root[4], b.root[5], b.root[6], b.root[3]);
    const q = this.firstRotation.slerp(this.secondRotation, mix);
    return {...nearest, time_s:this.time, root:[...a.root.slice(0, 3).map((v, j) => lerp(v, b.root[j], mix)), q.w, q.x, q.y, q.z],
      joints_rad:Object.fromEntries(Object.keys(a.joints_rad).map(id => [id, lerp(a.joints_rad[id], b.joints_rad[id], mix)]))};
  }
}
