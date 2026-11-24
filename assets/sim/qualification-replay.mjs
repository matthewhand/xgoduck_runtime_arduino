const MAX_REPORT_BYTES = 20 * 1024 * 1024;
const PHASES = {
  brake_turn:'Slowing for reverse', turn_around:'Turning around', reverse_seek:'Seeking backwards',
  walk:'Walking', default_pose:'Preparing to get up', getup:'Getting up',
  parking:'Landing (torque off)', parked:'Parked (torque off)', waking:'Torque on',
  lean_back:'Leaning back', step_left:'Lifting the left skate', step_right:'Lifting the right skate',
  step_settle:'Returning to skate stance', chair_rise:'Rising from the chair',
  approaching:'Backing in', sitting:'Lowering into the chair', approach_missed:'Missed the seat',
};
const LABELS = {stock:'Stock Duck', 'Nearly flat':'Parallel to support', bash:'Bash', 'bash-early':'Early Bash', 'bash-late':'Late Bash',
  back:'Back drop', front:'Front drop', left:'Left-side drop', right:'Right-side drop',
  'Before · Timed lowering':'Before · Fixed lowering point', 'After · Controlled lowering':'After · Speed-based lowering'};
export const LOWERING_PAIR = ['Before · Timed lowering', 'After · Controlled lowering'];
export const SKATE_TURN_LOOP = ['Rolling arc · Anticlockwise', 'Rolling arc · Clockwise', 'Standing pivot · Clockwise', 'Standing pivot · Anticlockwise'];
export const TURN_SEEK_LOOP = ['Feet · Clockwise', 'Feet · Anticlockwise', 'Skates · Turn and reverse'];
export const CLEAR_LANE_LOOP = ['Feet · Success', 'Feet · Failure', 'Skates · Success', 'Skates · Failure'];
export const TRIP_PAIR = ['Feet · Lean into trip bar', 'Skates · Step over trip bar'];
export const RELEASE_PAIR = ['Before · Clearance estimate', 'After · Upright and free of contact'];

const label = value => Object.hasOwn(LABELS, value) ? LABELS[value] : value.replace(/[-_]+/g, ' ');
const number = (value, digits, unit) => Number.isFinite(value) ? `${value.toFixed(digits)} ${unit}` : '—';
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);

export function mergeDockRecordings(recordings) {
  const report = {};
  for (const recording of recordings) {
    for (const [design, trials] of Object.entries(recording)) {
      report[design] = {...report[design], ...trials};
    }
  }
  return report;
}

export async function loadDockCase(index, scenario, readRecording) {
  const sources = Object.hasOwn(index, scenario) ? index[scenario] : null;
  if (!sources?.length) throw new Error('Unknown docking trial.');
  const recordings = await Promise.all(sources.map(readRecording));
  const report = mergeDockRecordings(recordings);
  return Object.fromEntries(Object.entries(report)
    .filter(([, trials]) => Object.hasOwn(trials, scenario))
    .map(([variant, trials]) => [variant, {[scenario]: trials[scenario]}]));
}

function validRamp(module) {
  if (module.ramp_deg === undefined) return true;
  const angle = Math.abs(module.ramp_deg);
  return !module.capsule_m && vector(module.size_m,3) && Number.isFinite(module.ramp_deg)
    && angle > 0 && angle < 90 && module.size_m[0] * Math.tan(angle * Math.PI / 180) < module.size_m[2];
}

function parseModules(modules) {
  if (modules === undefined) return [];
  if (!Array.isArray(modules) || modules.length > 64 || modules.some(module =>
    !object(module) || typeof module.name !== 'string' || typeof module.parent !== 'string'
    || !vector(module.center_m, 3)
    || (module.roll_deg !== undefined && !Number.isFinite(module.roll_deg))
    || (module.pitch_deg !== undefined && !Number.isFinite(module.pitch_deg))
    || (module.yaw_deg !== undefined && !Number.isFinite(module.yaw_deg))
    || !validRamp(module)
    || (module.capsule_m
      ? !vector(module.capsule_m, 2) || module.capsule_m[0] <= 0 || module.capsule_m[1] <= 2 * module.capsule_m[0]
      : !vector(module.size_m, 3) || module.size_m.some(size => size <= 0)))) {
    throw new Error('The report contains an invalid accessory shape.');
  }
  return modules;
}

export const usesSkates = result => Boolean(result?.skate || result?.dock?.skates);

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
            || (usesSkates(result) && !vector(frame.wheels_rad, 4))
            || !jointIds.every(id => Number.isFinite(frame.joints_rad?.[id]))) {
          throw new Error(`The recording for ${label(name)} has an invalid frame.`);
        }
        previousTime = frame.time_s;
        const onFootPad = result.dock && Array.isArray(frame.push_off)
          && frame.push_off.some(name => name === 'Left foot on foot pad' || name === 'Right foot on foot pad');
        for (const [event, time] of [
          ['Turn around', frame.recovery?.phase === 'turn_around' ? frame.time_s : null],
          ['Slow for reverse', frame.recovery?.phase === 'brake_turn' ? frame.time_s : null],
          ['Seek backwards', frame.recovery?.phase === 'reverse_seek' ? frame.time_s : null],
          ['Lean back', frame.recovery?.phase === 'lean_back' ? frame.time_s : null],
          ['Foot caught', result.dock?.bar_entry?.catch_s],
          ['Left step', frame.recovery?.phase === 'step_left' ? frame.time_s : null],
          ['Right step', frame.recovery?.phase === 'step_right' ? frame.time_s : null],
          ['Lower', frame.recovery?.phase === 'sitting' ? frame.time_s : null],
          [result.dock?.navigation && !result.dock.approach_reached ? result.dock.navigation.outcome : 'Missed seat', frame.recovery?.phase === 'approach_missed' ? frame.time_s : null],
          [result.dock?.chair ? 'Seated' : 'Parked', frame.recovery?.phase === 'parked' ? frame.time_s : null],
          ['Chair rise', frame.recovery?.phase === 'chair_rise' ? frame.time_s : null],
          ['Foot on pad', onFootPad ? frame.time_s : null],
          ['Push', frame.push?.time_s], ['Fall', result.dock ? null : frame.recovery?.fall_at_s],
          ['Get-up', frame.recovery?.getup_at_s],
          [result.dock?.skates ? 'Roll away' : 'Walk again', frame.recovery?.resumed_at_s],
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
    const elements = new Map([...element.querySelectorAll('[id^="qualification-"]')]
      .map(child => [child.id.slice('qualification-'.length), child]));
    this.get = key => elements.get(key);
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
    this.get('case').addEventListener('change', event => { void this.chooseCase(event.target.value); });
    this.get('variant').addEventListener('change', event => {
      this.get('alternate').checked = false;
      this.select(event.target.value, 'manual');
    });
    this.get('alternate').addEventListener('change', () => {
      if (this.alternating && !this.playlist.includes(this.selected)) {
        this.time = 0;
        this.select(this.playlist[0]);
      } else {
        this.updateDuration();
        this.updatePosition();
      }
    });
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
  get selectedLabel() { return label(this.selected); }
  get frame() { return this.trial && replayFrameAt(this.trial.result.trace, this.time); }
  get alternating() { return !this.get('alternate-label').hidden && this.get('alternate').checked; }

  setRecording(report, {scenario, variant, filename, alternate = false, dockIndex, dockLoader} = {}) {
    const cases = parseQualificationReport(report, this.jointIds);
    this.caseRequest = {};
    this.dockLoader = dockLoader;
    this.cases = cases;
    const options = dockIndex ? Object.keys(dockIndex) : [...cases.keys()];
    this.get('case').replaceChildren(...options.map(key => new Option(label(key), key)));
    this.get('case-field').hidden = options.length < 2;
    this.get('controls').hidden = false;
    this.get('status').textContent = filename ? `Loaded ${filename}` : '';
    this.get('alternate').checked = alternate;
    this.selectCase(cases.has(scenario) ? scenario : cases.keys().next().value, variant);
  }

  async chooseCase(next) {
    const request = this.caseRequest = {};
    const status = this.get('status');
    const preferred = this.trial?.result.dock ? this.selected : undefined;
    try {
      if (this.dockLoader && !this.cases.has(next)) {
        status.textContent = 'Loading the selected dock trial…';
        const report = await this.dockLoader(next);
        if (request !== this.caseRequest) return;
        const parsed = parseQualificationReport(report, this.jointIds);
        this.cases.set(next, parsed.get(next));
      }
      if (this.dockLoader) status.textContent = '';
      this.selectCase(next, preferred);
    } catch (error) {
      if (request !== this.caseRequest) return;
      this.get('case').value = this.case;
      status.textContent = error.message;
    }
  }

  async load(file, {scenario, variant} = {}) {
    const request = ++this.fileRequest;
    this.caseRequest = {};
    const message = this.get('status');
    try {
      if (file.size > MAX_REPORT_BYTES) throw new Error('Choose a report smaller than 20 MB.');
      message.textContent = 'Reading recording…';
      const report = JSON.parse(await file.text());
      if (request !== this.fileRequest) return;
      this.setRecording(report, {scenario, variant, filename:file.name});
      return true;
    } catch (error) {
      if (request === this.fileRequest) {
        message.textContent = error instanceof SyntaxError ? 'The file is not valid JSON.' : error.message;
      }
    }
  }

  selectCase(next, preferred) {
    this.case = next;
    this.get('case').value = next;
    this.trials = this.cases.get(next);
    this.time = 0;
    this.playlist = [LOWERING_PAIR, RELEASE_PAIR, TRIP_PAIR, CLEAR_LANE_LOOP, TURN_SEEK_LOOP, SKATE_TURN_LOOP].find(list => list.every(name => this.trials.has(name)));
    this.get('alternate-label').hidden = !this.playlist;
    this.get('variant').replaceChildren(...[...this.trials.keys()].map(key => new Option(label(key), key)));
    this.previousVariant = [...this.trials.keys()].find(key => key !== 'stock');
    const first = this.trials.has('stock') ? 'stock' : this.trials.keys().next().value;
    const preferredVariant = this.alternating && !this.playlist.includes(preferred) ? this.playlist[0] : preferred;
    this.select(this.trials.has(preferredVariant) ? preferredVariant : first, 'case');
  }

  updateDuration() {
    this.duration = this.alternating || this.trial.result.dock?.navigation || this.trial.result.dock?.qualification ? this.trial.duration : Math.max(...[...this.trials.values()].map(trial => trial.duration));
    this.get('seek').max = this.duration;
    this.time = Math.min(this.time, this.duration);
  }

  select(next, action = 'variant') {
    if (!this.trials.has(next)) return;
    this.selected = next;
    if (action === 'manual' && (this.trial.result.skate || this.trial.result.dock?.navigation || this.trial.result.dock?.qualification || this.trial.result.dock?.lowering_test || this.trial.result.dock?.bar_entry)) this.time = 0;
    this.updateDuration();
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
      jump.textContent = name === 'Roll away' ? 'Skating policy on' : name;
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

  advance(seconds, loop = false) {
    const next = this.time + seconds * Number(this.get('speed').value);
    if (loop && this.alternating && next >= this.duration) {
      this.time = next - this.duration;
      const index = (this.playlist.indexOf(this.selected) + 1) % this.playlist.length;
      this.select(this.playlist[index], 'loop');
      return true;
    }
    this.time = loop && this.duration > 0 ? next % this.duration : Math.min(next, this.duration);
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
    const skate = this.trial.result.skate;
    this.get('phase').textContent = skate ? skate.profile
      : phase === 'walk' && this.trial.result.dock?.skates ? 'Skating policy'
      : phase === 'approach_missed' && this.trial.result.dock?.navigation ? this.trial.result.dock.navigation.outcome
      : Object.hasOwn(PHASES, phase) ? PHASES[phase] : 'Recorded pose';
    const feet = frame?.footfalls;
    this.get('footfalls').parentElement.hidden = Boolean(skate);
    this.get('footfalls').textContent = Number.isInteger(feet?.left) && Number.isInteger(feet?.right)
      ? `${feet.left} left · ${feet.right} right` : '—';
    const contacts = frame?.module_contacts;
    this.get('contact-field').hidden = !this.trial.modules.length;
    this.get('contact').textContent = Array.isArray(contacts) && contacts.every(name => typeof name === 'string')
      ? contacts.map(label).join(', ') || 'None' : '—';
    const pushOff = frame?.push_off;
    this.get('pushoff-field').hidden = !this.trial.result.dock;
    this.get('pushoff').textContent = Array.isArray(pushOff) && pushOff.every(name => typeof name === 'string')
      ? pushOff.join(', ') : 'None';
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
    const currentDock = this.trial.result.dock;
    const allPadTrials = currentDock?.contact_force_n && !currentDock.stress_test && !currentDock.bar_entry && !currentDock.qualification && !currentDock.navigation ? [...this.cases.values()]
      .map(trials => trials.get(this.selected)?.result.dock).filter(dock => dock?.contact_force_n) : [];
    const approaches = allPadTrials.filter(dock => typeof dock.approach_reached === 'boolean');
    const departures = allPadTrials.filter(dock => dock.approach_reached === null);
    const rows = currentDock ? [
      ...(typeof this.trial.result.dock.approach_reached === 'boolean' ? [
        [currentDock.bar_entry ? 'Reached sitting position' : 'Reached chair', result => result.dock?.approach_reached ? 'Yes' : 'No'],
        ['Seated', result => result.dock?.seated ? 'Yes' : 'No'],
      ] : []),
      ...(currentDock.navigation ? [
        ['Outcome', result => result.dock.navigation.outcome],
        ...(currentDock.navigation.cohort ? [
          ['Reached heading / 9', result => String(result.dock.navigation.cohort.aligned)],
          ['Held heading for 0.4 s / 9', result => String(result.dock.navigation.cohort.held)],
          ['Slow enough to reverse while aligned / 9', result => String(result.dock.navigation.cohort.ready)],
          ['Speed at first alignment', result => number(result.dock.navigation.speed_at_heading, 2, 'm/s')],
        ] : []),
        ['Rotation in requested direction', result => number(result.dock.navigation.turned_deg, 1, '°')],
        ['Starting heading', result => number(result.dock.navigation.start_deg, 0, '°')],
        ['Distance closed in reverse', result => number(result.dock.navigation.reverse_m * 100, 1, 'cm')],
      ] : []),
      ...(currentDock.qualification ? [
        ['Clean exits in cohort', result => `${result.dock.qualification.cohort_clean} / 100 (target 95)`],
        ['Trial', result => `#${result.dock.qualification.id} · ${result.dock.qualification.outcome}`],
        ['Lateral offset / yaw', result => `${result.dock.qualification.lateral_mm.toFixed(1)} mm / ${result.dock.qualification.yaw_deg.toFixed(1)}°`],
        ['Approach speed', result => number(result.dock.qualification.speed_mps, 3, 'm/s')],
        ['Sliding friction coefficient', result => number(result.dock.qualification.ground_grip, 2, '')],
        ['Receiver mass', result => number(result.dock.qualification.receiver_g, 1, 'g')],
      ] : []),
      ...(currentDock.bar_entry ? [
        ['Bar height × span', result => `${result.dock.bar_entry.bar_mm} × ${result.dock.bar_entry.span_mm} mm`],
        ...(currentDock.skates && currentDock.bar_entry.step_commanded ? [
          ['Skates fully across during step', result => result.dock.bar_entry.skates_across.join(', ') || 'Neither'],
          ['Wheel lift (left / right)', result => {
            const lift = result.dock.bar_entry.lift_mm;
            return `${lift.left ?? 0} / ${lift.right ?? 0} mm`;
          }],
          ['Bar struck during step', result => result.dock.bar_entry.bar_hit_during_step ? 'Yes' : 'No'],
        ] : currentDock.skates ? [] : [
          ['Foot caught during backward lean', result => result.dock.bar_entry.leaned_on_bar ? 'Yes' : 'No'],
          ['Pitch while braced', result => number(result.dock.bar_entry.pitch_on_bar_deg, 1, '°')],
        ]),
        ['Docked and exited forward', result => result.dock.bar_entry.dock_and_exit ? 'Yes' : 'No'],
      ] : []),
      ...(currentDock.stress_test ? [
        ...(typeof currentDock.approach_reached === 'boolean' ? [
          ['Initial approach speed', result => number(result.dock?.approach_speed_mps, 2, 'm/s')],
        ] : []),
        ['Wheel friction', result => number(result.dock?.wheel_grip, 2, '')],
        ['Seated pose screen', result => result.dock?.pose_screen ?
          (result.dock.pose_screen.matches ? 'Matches' : 'Outside range') : '—'],
      ] : []),
      ...(currentDock.lowering_test ? [
        ['Seat lip angle', result => `${result.dock.seat_lip_deg}°`],
        ['Speed as lowering starts', result => number(result.dock?.lowering_speed_mps, 3, 'm/s')],
        ['Seated body pitch', result => number(result.dock?.pose_screen?.pitch_deg, 1, '°')],
        ['Clean docking and exit', result => result.passed ? 'Passed' : 'Failed'],
      ] : []),
      ...(this.trial.result.dock.contact_force_n ? [
        ['Backrest', result => number(result.dock?.backrest_deg, 0, '°')],
        ...(currentDock.settling_s ? [['Settle before release', result => number(result.dock?.settling_s, 1, 's')]] : []),
        ...(this.trial.result.dock.approach_reached === null ? [] : [
          [currentDock.bar_entry ? 'Entry maneuver trigger' : 'Start lowering at', result => number(result.dock?.seat_trigger_m * 1000, 0, 'mm')],
        ]),
        ['Both pads loaded', result => result.dock?.pads_loaded ? 'Yes' : 'No'],
        ['Left pad', result => number(result.dock?.contact_force_n?.Left, 2, 'N')],
        ['Right pad', result => number(result.dock?.contact_force_n?.Right, 2, 'N')],
        ...(approaches.length ? [['Approaches that loaded both pads',
          () => `${approaches.filter(dock => dock.pads_loaded).length} / ${approaches.length}`],
        ['Full cycles within 25° side tilt', () => `${approaches.filter(dock =>
          dock.pads_loaded && dock.recovered && dock.side_tilt_deg <= 25).length} / ${approaches.length}`]] : []),
        ...(departures.length ? [['Seated exits within 25° side tilt',
          () => `${departures.filter(dock => dock.recovered && dock.side_tilt_deg <= 25).length} / ${departures.length}`]] : []),
      ] : [
        ['Coil geometry', result => result.dock?.aligned ? 'Within tolerance' : 'Outside tolerance'],
        ['Coil offset', result => number(result.dock?.offset_mm, 1, 'mm')],
        ['Coil tilt', result => number(result.dock?.tilt_deg, 1, '°')],
        ['Coil gap', result => number(result.dock?.gap_mm, 1, 'mm')],
      ]),
      [currentDock.bar_entry ? 'Time to resume locomotion' : 'Rise and leave', result => result.dock?.recovered ? number(result.recovered_s, 2, 's') : 'Failed'],
      ['Along tray', result => {
        const headward = result.dock?.headward_mm;
        if (!Number.isFinite(headward)) return '—';
        return `${Math.abs(headward)} mm ${headward < 0 ? 'toward feet' : 'toward head'}`;
      }],
      ['Sideways', result => number(result.dock?.sideways_mm, 0, 'mm')],
      ['Peak side tilt', result => number(result.dock?.side_tilt_deg, 1, '°')],
      ...(currentDock.roller_release ? [
        ...(Number.isFinite(currentDock.roller_release.chair_clearance_mm) ? [
          ['Clearance at end of rise', result => number(result.dock?.roller_release?.chair_clearance_mm, 1, 'mm')],
        ] : []),
        ['Forward travel after handoff', result => number(result.dock?.roller_release?.after_handoff_m, 2, 'm')],
        ['Floor brace', result => result.dock?.roller_release?.floor_contacts?.join(', ') || 'None detected'],
        ...(Array.isArray(currentDock.roller_release.exit_chair_contacts) ? [
          ['Chair contact while skating', result => result.dock.roller_release.handoff
            ? result.dock.roller_release.exit_chair_contacts.join(', ') || 'None detected' : 'Policy did not start'],
        ] : []),
      ] : []),
    ] : this.trial.result.skate ? [
      ['Forward command', result => number(result.skate.command_m_s, 2, 'm/s')],
      ['Forward distance', result => number(result.forward_m, 2, 'm')],
      ['Average speed', result => number(result.average_m_s, 2, 'm/s')],
      ['Peak speed over 0.5 s', result => number(result.peak_half_second_m_s, 2, 'm/s')],
      ['Maximum sideways drift', result => number(result.max_side_m * 100, 1, 'cm')],
      ['Clean runs', result => result.skate.total ? `${result.skate.clean} / ${result.skate.total}` : '—'],
    ] : [
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
