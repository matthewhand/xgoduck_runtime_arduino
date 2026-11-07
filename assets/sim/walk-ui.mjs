const $ = id => document.getElementById(id);
const active = state => ['loading', 'running', 'stopping'].includes(state);
const fmt = (value, digits, unit) => Number.isFinite(value) ? value.toFixed(digits) + unit : '—';
const fields = {
  loading: 'Loading the ONNX policy and MuJoCo…',
  running: 'Trial running on the UNO Q CPU.',
  stopping: 'Stopping the trial…',
  stopped: 'Trial stopped.',
  complete: 'Trial complete.',
  fallen: 'The simulated Duck fell. Try a different command.',
};

export class WalkPanel {
  constructor() {
    this.history = [];
    this.latest = null;
    this.lastSeen = 0;
    this.requestId = 0;
    this.visible = false;
    this.timer = null;
    this.pending = false;
    this.error = '';
    for (const [key, unit] of [['vx', ' m/s'], ['yaw', ' rad/s']]) {
      const input = $('walk-' + key);
      input.addEventListener('input', () => {
        $('walk-' + key + '-value').textContent = fmt(Number(input.value), 2, unit);
      });
    }
    $('walk-start').addEventListener('click', () => this.action('start',
      {vx:Number($('walk-vx').value), yaw:Number($('walk-yaw').value)}));
    $('walk-stop').addEventListener('click', () => this.action('stop', {}));
  }

  setVisible(visible) {
    if (visible === this.visible) return;
    this.visible = visible;
    this.error = '';
    if (visible) this.poll();
    else {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  async request(suffix = '', body) {
    const id = ++this.requestId;
    const options = {cache:'no-store', signal:AbortSignal.timeout(1800)};
    if (body) Object.assign(options, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
    });
    const response = await fetch('/api/lab/walk' + suffix, options);
    const sample = await response.json().catch(() => null);
    if (!response.ok || !sample) throw new Error(sample?.detail || 'Walking trial service is unavailable.');
    if (id !== this.requestId) return;
    this.latest = sample;
    this.lastSeen = performance.now();
  }

  async action(name, body) {
    this.pending = true;
    this.error = '';
    this.update();
    try { await this.request('/' + name, body); }
    catch (error) { this.error = error.message; }
    finally {
      this.pending = false;
      this.update();
      if (this.visible) {
        clearTimeout(this.timer);
        this.poll();
      }
    }
  }

  async poll() {
    if (!this.visible || this.polling) return;
    this.polling = true;
    try {
      if (!document.hidden && !this.pending) await this.request();
    } catch { /* Age out metrics when the connection stops responding. */ }
    finally {
      this.polling = false;
      this.update();
      if (this.visible) this.timer = setTimeout(() => this.poll(),
        !document.hidden && active(this.latest?.state) ? 95 : 850);
    }
  }

  update() {
    const fresh = performance.now() - this.lastSeen < 2400;
    const run = fresh ? this.latest : null;
    const busy = active(run?.state);
    $('walk-state').textContent = this.error || (!run ? 'Waiting for the UNO Q…'
      : !run.available ? 'Install headless MuJoCo on the UNO Q to enable walking trials.'
      : run.state === 'error' ? run.detail
      : fields[run.state] || 'Run the shipped walking policy on the UNO Q for up to 20 seconds.');
    $('walk-start').disabled = !run?.available || busy || this.pending;
    $('walk-stop').disabled = !busy || run.state === 'stopping' || this.pending;
    $('walk-vx').disabled = busy;
    $('walk-yaw').disabled = busy;
    $('walk-hz').textContent = fmt(run?.hz, 1, ' Hz');
    $('walk-inference').textContent = fmt(run?.inference_ms, 2, ' ms');
    $('walk-work').textContent = fmt(run?.slot_p95_ms, 2, ' / 20 ms');
    $('walk-path').textContent = fmt(run?.path_m, 2, ' m');
    $('walk-missed').textContent = run?.missed ?? '—';
    $('walk-duck-missed').textContent = run?.board_missed_delta ?? '—';
    $('walk-missed').classList.toggle('warning', run?.missed > 0);
    $('walk-duck-missed').classList.toggle('warning', run?.board_missed_delta > 0);
    $('hud-misses').textContent = run?.missed == null ? '—' : `${run.missed} sim · ${run.board_missed_delta ?? '—'} Duck`;
    $('hud-misses').classList.toggle('warning', run?.missed > 0 || run?.board_missed_delta > 0);
  }

  recordBoard(sample) {
    const {cpu, gpu} = sample || {};
    this.history.push({
      time: performance.now(),
      cpu: cpu?.available ? cpu.load_percent : null,
      core: cpu?.available ? cpu.busiest_core_percent : null,
      gpu: gpu?.available ? gpu.load_percent : null,
    });
    const now = this.history.at(-1).time;
    this.history = this.history.filter(row => now - row.time <= 30000);
    for (const key of ['cpu', 'core', 'gpu']) {
      let drawing = false, path = '', previous = 0;
      for (const row of this.history) {
        const value = row[key];
        if (!Number.isFinite(value)) { drawing = false; continue; }
        const x = 290 * (1 - (now - row.time) / 30000), y = 68 - Math.max(0, Math.min(100, value)) * 0.66;
        path += `${drawing && row.time - previous < 2500 ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)} `;
        drawing = true; previous = row.time;
      }
      $('walk-' + key + '-path').setAttribute('d', path);
      $('walk-' + key).textContent = fmt(this.history.at(-1)[key], 1, '%');
      $('hud-' + key).textContent = fmt(this.history.at(-1)[key], 0, '%');
    }
  }
}
