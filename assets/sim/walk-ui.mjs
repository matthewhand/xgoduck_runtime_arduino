const $ = id => document.getElementById(id);
const active = state => ['loading', 'running', 'stopping'].includes(state);
const fmt = (value, digits, unit) => Number.isFinite(value) ? value.toFixed(digits) + unit : '—';
const fields = {
  loading: 'Loading the ONNX policy and MuJoCo…',
  running: 'Trial running on the UNO Q CPU.',
  stopping: 'Stopping the trial…',
  stopped: 'Trial stopped.',
  complete: 'Trial complete.',
  found: 'Beacon found.',
  fallen: 'The simulated Duck fell. Try a different command.',
};

export class WalkPanel {
  constructor() {
    this.history = [];
    this.latest = null;
    this.lastSeen = 0;
    this.requestId = 0;
    this.visible = false;
    this.explore = false;
    this.timer = null;
    this.pending = false;
    this.error = '';
    for (const [key, unit] of [['vx', ' m/s'], ['yaw', ' rad/s']]) {
      const input = $('walk-' + key);
      input.addEventListener('input', () => {
        $('walk-' + key + '-value').textContent = fmt(Number(input.value), 2, unit);
      });
    }
    $('walk-start').addEventListener('click', () => this.action('start', this.explore
      ? {arena:$('search-arena').value}
      : {vx:Number($('walk-vx').value), yaw:Number($('walk-yaw').value)}));
    $('walk-stop').addEventListener('click', () => this.action('stop', {}));
  }

  setMode(mode) {
    this.explore = mode === 'explore';
    $('walk-title').textContent = this.explore ? 'Beacon hunt' : 'Walking policy';
    $('walk-start').textContent = this.explore ? 'Start search' : 'Run 20 s';
    $('walk-inputs').hidden = this.explore;
    $('search-inputs').hidden = $('search-map-panel').hidden = !this.explore;
    this.setVisible(mode === 'walk' || this.explore);
    this.update();
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
    const matching = Boolean(run?.arena) === this.explore;
    const searchState = {running:'Scanning and choosing a route.', complete:'Time ran out before the beacon was seen.'};
    $('walk-state').textContent = this.error || (!run ? 'Waiting for the UNO Q…'
      : !run.available ? 'Install headless MuJoCo on the UNO Q to enable walking trials.'
      : !matching && busy ? (run.arena ? 'A search is active in Explore.' : 'A walking trial is active.')
      : matching && run.state === 'error' ? run.detail
      : (matching && ((this.explore && searchState[run.state]) || fields[run.state]))
        || (this.explore ? 'The Duck scans nearby space and explores until it spots the beacon.'
          : 'Run the shipped walking policy on the UNO Q for up to 20 seconds.'));
    $('walk-start').disabled = !run?.available || busy || this.pending;
    $('walk-stop').disabled = !busy || run.state === 'stopping' || this.pending;
    $('walk-vx').disabled = busy;
    $('walk-yaw').disabled = busy;
    $('search-arena').disabled = busy;
    const trial = matching ? run : null;
    $('walk-hz').textContent = fmt(trial?.hz, 1, ' Hz');
    $('walk-inference').textContent = fmt(trial?.inference_ms, 2, ' ms');
    $('walk-work').textContent = fmt(trial?.slot_p95_ms, 2, ' / 20 ms');
    $('walk-path').textContent = fmt(trial?.path_m, 2, ' m');
    $('walk-missed').textContent = trial?.missed ?? '—';
    $('walk-duck-missed').textContent = trial?.board_missed_delta ?? '—';
    $('walk-missed').classList.toggle('warning', trial?.missed > 0);
    $('walk-duck-missed').classList.toggle('warning', trial?.board_missed_delta > 0);
    $('hud-misses').textContent = trial?.missed == null ? '—' : `${trial.missed} sim · ${trial.board_missed_delta ?? '—'} Duck`;
    $('hud-misses').classList.toggle('warning', trial?.missed > 0 || trial?.board_missed_delta > 0);
    if (this.explore) drawMap(run?.mission, run?.root);
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

function drawMap(map, root) {
  const canvas = $('search-map');
  const ctx = canvas.getContext('2d');
  const {width, height} = canvas;
  ctx.fillStyle = '#0b1720';
  ctx.fillRect(0, 0, width, height);
  $('search-coverage').textContent = map ? `${map.mapped_percent}% MAPPED` : 'AWAITING SCAN';
  if (!map) {
    canvas.setAttribute('aria-label', 'Range map awaiting the first scan.');
    return;
  }
  const tile = width / map.cols;
  const colors = ['#15232e', '#24444b', '#bd7958'];
  for (let i = 0; i < map.grid.length; i++) {
    const col = i % map.cols, row = Math.floor(i / map.cols);
    ctx.fillStyle = colors[Number(map.grid[i])];
    ctx.fillRect(col * tile, height - (row + 1) * tile, tile - 1, tile - 1);
  }
  const point = ([x, y]) => [(x - map.origin[0]) * tile / map.cell_m, height - (y - map.origin[1]) * tile / map.cell_m];
  const dot = (pos, color, radius) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(...point(pos), radius, 0, Math.PI * 2);
    ctx.fill();
  };
  if (map.trail.length) {
    ctx.beginPath();
    ctx.moveTo(...point(map.trail[0]));
    for (const pos of map.trail.slice(1)) ctx.lineTo(...point(pos));
    ctx.strokeStyle = '#8edac8';
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  if (map.beacon) dot(map.beacon, '#ffcb72', 6);
  else if (map.waypoint) dot(map.waypoint, '#90aafa', 3);
  if (root) dot(root, '#d8fff3', 5);
  canvas.setAttribute('aria-label', `Range map, ${map.mapped_percent}% mapped. ${map.beacon ? 'Beacon found.' : 'Searching for beacon.'}`);
}
