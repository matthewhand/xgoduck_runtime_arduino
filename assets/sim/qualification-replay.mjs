const MAX_REPORT_BYTES = 20 * 1024 * 1024;
const PHASES = {walk:'Walking', default_pose:'Preparing to get up', getup:'Getting up'};
const LABELS = {stock:'Stock Duck', bash:'Bash', 'bash-early':'Early Bash', 'bash-late':'Late Bash',
  back:'Back drop', front:'Front drop', left:'Left-side drop', right:'Right-side drop'};

const label = value => Object.hasOwn(LABELS, value) ? LABELS[value] : value.replace(/[-_]+/g, ' ');
const number = (value, digits, unit) => Number.isFinite(value) ? `${value.toFixed(digits)} ${unit}` : '—';
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);

function parseModules(modules) {
  if (modules === undefined) return [];
  if (!Array.isArray(modules) || modules.length > 64 || modules.some(module =>
    !object(module) || typeof module.name !== 'string' || typeof module.parent !== 'string'
    || !vector(module.center_m, 3)
    || (module.capsule_m
      ? !vector(module.capsule_m, 2) || module.capsule_m[0] <= 0 || module.capsule_m[1] <= 2 * module.capsule_m[0]
      : !vector(module.size_m, 3) || module.size_m.some(size => size <= 0)))) {
    throw new Error('The report contains an invalid accessory shape.');
  }
  return modules;
}

export function parseQualificationReport(report, jointIds) {
  const cases = new Map();
  if (!object(report)) throw new Error('Choose a hardware qualification JSON report.');
  for (const [name, trials] of Object.entries(report)) {
    if (!object(trials)) continue;
    for (const [test, result] of Object.entries(trials)) {
      if (!Array.isArray(result?.trace)) continue;
      if (!result.trace.length) throw new Error(`The recording for ${label(name)} is empty.`);
      let previousTime = -1;
      const events = new Map();
      for (const frame of result.trace) {
        if (!Number.isFinite(frame?.time_s) || frame.time_s < 0 || frame.time_s <= previousTime
            || !vector(frame.root, 7)
            || Math.abs(Math.hypot(...frame.root.slice(3)) - 1) > 0.001
            || !jointIds.every(id => Number.isFinite(frame.joints_rad?.[id]))) {
          throw new Error(`The recording for ${label(name)} has an invalid frame.`);
        }
        previousTime = frame.time_s;
        for (const [event, time] of [
          ['Push', frame.push?.time_s], ['Fall', frame.recovery?.fall_at_s],
          ['Get-up', frame.recovery?.getup_at_s], ['Walk again', frame.recovery?.resumed_at_s],
        ]) {
          if (!events.has(event) && Number.isFinite(time) && time >= 0 && time <= frame.time_s) {
            // The runner records after stepping, so an event timestamp may
            // precede the first pose that actually shows it.
            events.set(event, frame.time_s);
          }
        }
      }
      if (!cases.has(test)) cases.set(test, new Map());
      cases.get(test).set(name, {result, events, duration:previousTime, modules:parseModules(result.modules)});
    }
  }
  if (!cases.size) throw new Error('This report has no recorded poses. Generate it with --trace-case.');
  return cases;
}

export function replayFrameAt(trace, time) {
  let lo = 0, hi = trace.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (trace[mid].time_s <= time) lo = mid;
    else hi = mid - 1;
  }
  return trace[lo];
}

export class QualificationReplay {
  constructor(element, jointIds, onChange) {
    this.get = key => element.querySelector(`#qualification-${key}`);
    this.jointIds = jointIds;
    this.onChange = onChange;
    this.time = 0;
    this.duration = 0;
    this.selected = null;
    this.case = null;
    this.fileRequest = 0;
    this.lastDisplay = null;
    this.get('open').addEventListener('click', () => this.get('file').click());
    this.get('file').addEventListener('change', event => {
      const file = event.target.files[0];
      event.target.value = '';
      if (file) void this.load(file);
    });
    this.get('case').addEventListener('change', event => this.selectCase(event.target.value));
    this.get('variant').addEventListener('change', event => this.select(event.target.value));
    this.get('stock').addEventListener('click', () => {
      if (this.selected !== 'stock') {
        this.previousVariant = this.selected;
        this.select('stock');
      } else {
        this.select(this.previousVariant);
      }
    });
    this.get('seek').addEventListener('input', event => this.seek(Number(event.target.value)));
  }

  get trial() { return this.trials?.get(this.selected); }
  get frame() { return this.trial && replayFrameAt(this.trial.result.trace, this.time); }

  async load(file) {
    const request = ++this.fileRequest;
    const message = this.get('status');
    try {
      if (file.size > MAX_REPORT_BYTES) throw new Error('Choose a report smaller than 20 MB.');
      message.textContent = 'Reading recording…';
      const cases = parseQualificationReport(JSON.parse(await file.text()), this.jointIds);
      if (request !== this.fileRequest) return;
      this.cases = cases;
      this.get('case').replaceChildren(...[...cases.keys()].map(key => new Option(label(key), key)));
      this.get('case-field').hidden = cases.size < 2;
      this.get('controls').hidden = false;
      message.textContent = `Loaded ${file.name}`;
      this.selectCase(cases.keys().next().value);
    } catch (error) {
      if (request === this.fileRequest) {
        message.textContent = error instanceof SyntaxError ? 'The file is not valid JSON.' : error.message;
      }
    }
  }

  selectCase(next) {
    this.case = next;
    this.trials = this.cases.get(next);
    this.time = 0;
    this.duration = Math.max(...[...this.trials.values()].map(trial => trial.duration));
    this.get('seek').max = this.duration;
    this.get('variant').replaceChildren(...[...this.trials.keys()].map(key => new Option(label(key), key)));
    this.previousVariant = [...this.trials.keys()].find(key => key !== 'stock');
    this.select(this.trials.has('stock') ? 'stock' : this.trials.keys().next().value, 'case');
  }

  select(next, action = 'variant') {
    if (!this.trials.has(next)) return;
    this.selected = next;
    if (next !== 'stock') this.previousVariant = next;
    this.get('variant').value = next;
    const compare = this.get('stock');
    compare.hidden = !this.trials.has('stock') || !this.previousVariant;
    compare.textContent = next === 'stock' ? 'Show variant' : 'Show stock';
    const jumps = this.get('events');
    jumps.replaceChildren();
    for (const [name, time] of this.trial.events) {
      const jump = document.createElement('button');
      jump.type = 'button';
      jump.textContent = name;
      jump.title = `Jump to ${time.toFixed(2)} s`;
      jump.addEventListener('click', () => this.seek(time));
      jumps.append(jump);
    }
    this.updateMetrics();
    this.updatePosition();
    this.onChange(action);
  }

  seek(time) {
    this.time = Math.max(0, Math.min(time, this.duration));
    this.updatePosition();
    this.onChange('seek');
  }

  advance(seconds) {
    this.time = Math.min(this.time + seconds * Number(this.get('speed').value), this.duration);
    this.updatePosition();
    return this.time < this.duration;
  }

  updatePosition() {
    this.get('seek').value = this.time;
    const frame = this.frame;
    const text = `${this.time.toFixed(2)} / ${this.duration.toFixed(2)} s`;
    if (this.get('time').textContent !== text) this.get('time').textContent = text;
    if (frame === this.lastDisplay) return;
    this.lastDisplay = frame;
    const phase = frame?.recovery?.phase;
    this.get('phase').textContent = Object.hasOwn(PHASES, phase) ? PHASES[phase] : 'Recorded pose';
    const feet = frame?.footfalls;
    this.get('footfalls').textContent = Number.isInteger(feet?.left) && Number.isInteger(feet?.right)
      ? `${feet.left} left · ${feet.right} right` : '—';
    const contacts = frame?.module_contacts;
    this.get('contact-field').hidden = !this.trial.modules.length;
    this.get('contact').textContent = Array.isArray(contacts) && contacts.every(name => typeof name === 'string')
      ? contacts.map(label).join(', ') || 'None' : '—';
  }

  updateMetrics() {
    const comparison = this.trials.has('stock') && this.previousVariant;
    const names = comparison ? ['stock', this.previousVariant] : [this.selected];
    const headings = names.map(name => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = label(name);
      return th;
    });
    this.get('head').replaceChildren(document.createElement('td'), ...headings);
    const rows = [
      ['Result', result => result.passed === true ? 'Passed' : result.passed === false ? 'Failed' : '—'],
      ['Total mass', result => number(result.mass_g, 0, 'g')],
      ['Peak tilt', result => number(result.peak_tilt_deg, 1, '°')],
      ['Recovery', result => number(result.recovered_s, 2, 's')],
    ];
    this.get('metrics').replaceChildren(...rows.map(([name, value]) => {
      const row = document.createElement('tr');
      const th = document.createElement('th');
      th.scope = 'row';
      th.textContent = name;
      row.append(th);
      for (const trial of names) {
        const td = document.createElement('td');
        td.textContent = value(this.trials.get(trial).result);
        row.append(td);
      }
      return row;
    }));
  }
}
