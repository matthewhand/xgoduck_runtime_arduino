import {mountTrialExport} from './trial-report.mjs?v=2';

const endpoint = '/api/lab/physical';
const $ = id => document.getElementById(id);
const start = $('physical-start'), stop = $('physical-stop'), note = $('physical-state');
const actionNote = $('physical-action-result');
const setExport = mountTrialExport($('physical-export'), $('physical-export-result'), endpoint + '/report');
let current = null, pending = false, polling = false, actionCount = 0;

function render() {
  start.disabled = !current?.can_start || pending;
  stop.disabled = !current?.recording || pending;
  setExport(current?.report_run_key ?? null);
  if (current?.recording) {
    note.textContent = `Recording · ${current.elapsed_s.toFixed(1)} s · ${current.walking ? 'Stock policy active' : 'Waiting for Walk / get up'}`;
  } else {
    const saved = {complete:'Capture saved.', interrupted:'Interrupted capture saved.', no_motion:'Capture ended before the stock policy ran.'};
    note.textContent = current?.blocked || saved[current?.report_state]
      || (current ? 'Ready to capture.' : 'Waiting for the UNO Q…');
  }
}

async function request(path = '', body) {
  const options = {cache:'no-store', signal:AbortSignal.timeout(2000)};
  if (body) Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const response = await fetch(endpoint + path, options);
  const sample = await response.json();
  if (!response.ok) throw new Error(sample?.detail || 'Physical capture is unavailable.');
  return sample;
}

async function action(path, body) {
  if (pending) return;
  pending = true;
  actionCount++;
  actionNote.textContent = '';
  render();
  try { current = await request(path, body); }
  catch (error) { actionNote.textContent = error.message; }
  finally { pending = false; render(); }
}

start.addEventListener('click', () => action('/start', {}));
stop.addEventListener('click', () => action('/stop', {run_key:current?.run_key}));

async function poll() {
  if (document.hidden || polling || pending) return;
  polling = true;
  const before = actionCount;
  try {
    const sample = await request();
    if (before === actionCount) current = sample;
  } catch { if (before === actionCount) current = null; }
  finally { polling = false; render(); }
}

poll();
setInterval(poll, 1000);
