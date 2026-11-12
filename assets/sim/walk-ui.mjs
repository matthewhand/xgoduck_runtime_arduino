const $ = id => document.getElementById(id);
const active = state => ['loading', 'running', 'stopping'].includes(state);
const fmt = (value, digits, unit) => Number.isFinite(value) ? value.toFixed(digits) + unit : '—';
const fields = {
  loading: 'Loading the ONNX policies and MuJoCo…',
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
      : {vx:Number($('walk-vx').value), yaw:Number($('walk-yaw').value), pond:$('walk-pond').checked}));
    $('walk-stop').addEventListener('click', () => this.action('stop', {}));
    this.pushButtons = document.querySelectorAll('[data-walk-push]');
    for (const button of this.pushButtons) {
      button.addEventListener('click', () => this.action('push', {
        run_id: this.latest.run_id, kind: button.dataset.walkPush,
      }));
    }
  }

  get arena() {
    return this.demoArena ?? $('search-arena').value;
  }

  setMode(mode, demo = false, arena = null) {
    this.explore = mode === 'explore';
    this.demoArena = demo && this.explore ? arena : null;
    $('walk-inputs').hidden = this.explore || demo;
    $('walk-push-controls').hidden = this.explore;
    $('search-inputs').hidden = !this.explore || demo;
    $('search-map-panel').hidden = !this.explore;
    $('walk-action-buttons').hidden = $('walk-push-buttons').hidden = demo;
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
    return sample;
  }

  async action(name, body) {
    this.pending = true;
    this.error = '';
    this.update();
    try { return await this.request('/' + name, body); }
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
    const matching = this.explore ? run?.arena === this.arena : !run?.arena;
    const trial = matching ? run : null;
    const delivery = this.explore && this.arena === 'delivery';
    $('walk-title').textContent = this.explore ? (delivery ? 'Pond delivery' : 'Beacon hunt') : 'Walking policy';
    $('walk-start').textContent = this.explore ? (delivery ? 'Start delivery' : 'Start search') : 'Run 20 s';
    const recovery = trial?.recovery;
    const searchState = {loading:'Loading the walking policy and MuJoCo…',
      running:'Scanning and choosing a route.', complete:delivery ? 'Time ran out before the last delivery.' : 'Time ran out before the beacon was seen.',
      found:delivery ? 'Deliveries complete.' : fields.found};
    let walkState = '';
    if (!this.explore && trial?.state === 'fallen') walkState = 'Time ran out before the Duck stood back up.';
    if (!this.explore && trial?.state === 'running') {
      if (recovery?.phase === 'default_pose') walkState = 'Fall detected. Holding the recovery pose.';
      else if (recovery?.phase === 'getup') walkState = 'Get-up policy active · xgoduck_getup.onnx';
      else if (recovery?.resumed_at_s != null) walkState = `Walking again since ${fmt(recovery.resumed_at_s, 2, ' s')}.`;
    }
    $('walk-state').textContent = this.error || (!run ? 'Waiting for the UNO Q…'
      : !run.available ? 'Install headless MuJoCo on the UNO Q to enable walking trials.'
      : !matching && busy ? (run.arena ? 'A search is active in Explore.' : 'A walking trial is active.')
      : matching && run.state === 'error' ? run.detail
      : (matching && (walkState || (this.explore && searchState[run.state]) || fields[run.state]))
        || (this.explore ? (delivery ? 'Deliver to the jetty and boathouse around the divider.' : 'The Duck scans nearby space and explores until it spots the beacon.')
          : 'Run the shipped walking policy on the UNO Q for up to 20 seconds.'));
    $('walk-start').disabled = !run?.available || busy || this.pending;
    $('walk-stop').disabled = !busy || run.state === 'stopping' || this.pending;
    $('walk-vx').disabled = busy;
    $('walk-yaw').disabled = busy;
    $('walk-pond').disabled = busy;
    $('search-arena').disabled = busy;
    const push = trial?.push;
    const canPush = !this.explore && trial?.state === 'running' && !this.pending
      && (!recovery || recovery.phase === 'walk') && !trial.push_pending && (!push || push.recovery_s != null);
    for (const button of this.pushButtons) button.disabled = !canPush;
    let pushText = 'Poke and Nudge test balance. Bash can knock the Duck over.';
    if (trial?.push_pending) pushText = 'Push queued…';
    else if (push) {
      const label = push.kind[0].toUpperCase() + push.kind.slice(1);
      let outcome = busy ? 'checking balance…' : 'trial ended before recovery';
      if (push.recovery_s != null) outcome = `${push.fell ? 'back walking' : 'recovered'} in ${fmt(push.recovery_s, 2, ' s')}`;
      else if (busy && push.fell) outcome = 'getting back up…';
      pushText = `${label} at ${fmt(push.time_s, 2, ' s')} · ${outcome} · peak tilt ${fmt(push.peak_tilt_deg, 1, '°')}`;
    }
    $('walk-push-state').textContent = pushText;
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
    if (this.explore) {
      const progress = trial?.mission?.delivery;
      $('delivery-progress').hidden = !delivery;
      $('search-destination').textContent = delivery ? 'Station / planned route' : 'Beacon';
      $('delivery-progress').textContent = progress
        ? `${progress.delivered}/${progress.stations.length} delivered${progress.stations[progress.delivered] ? ` · Next: ${progress.stations[progress.delivered][0]}` : ''}`
        : 'Route starts at the jetty.';
      drawMap(trial?.mission, trial?.root);
    }
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
  const tile = Math.min(width / map.cols, height / map.rows);
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
  if (map.delivery) {
    const {stations, delivered, plan} = map.delivery;
    if (root && plan.length) {
      ctx.beginPath(); ctx.moveTo(...point(root));
      for (const cell of plan) ctx.lineTo(...point(cell));
      ctx.strokeStyle = '#ffcb72'; ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]);
    }
    for (const [index, [, x, y]] of stations.entries()) {
      dot([x, y], index < delivered ? '#8edac8' : '#ffcb72', 8);
      const [px, py] = point([x, y]);
      ctx.fillStyle = '#12232b'; ctx.font = 'bold 10px sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(String(index + 1), px, py);
    }
  } else if (map.beacon) dot(map.beacon, '#ffcb72', 6);
  else if (map.waypoint) dot(map.waypoint, '#90aafa', 3);
  if (root) dot(root, '#d8fff3', 5);
  const state = map.delivery ? `${map.delivery.delivered} of ${map.delivery.stations.length} deliveries complete.`
    : map.beacon ? 'Beacon found.' : 'Searching for beacon.';
  canvas.setAttribute('aria-label', `Range map, ${map.mapped_percent}% mapped. ${state}`);
}
