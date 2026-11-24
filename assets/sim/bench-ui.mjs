import {benchSnapshot, comparisonRows, readBenchSnapshot} from './bench-data.mjs?v=1';
import {downloadJson, readRelease} from './trial-report.mjs?v=3';

const $ = id => document.getElementById('bench-' + id);
const format = (value, digits, unit = '') => Number.isFinite(value) ? value.toFixed(digits) + unit : '—';
const formatVector = value => value ? value.map(v => v.toFixed(2)).join(', ') : '—';
const idList = value => value.join(', ') || 'None';
let current = null, saved = null;
let release = null, polling = false;
readRelease().then(stamp => { release = stamp?.commit ?? null; });

function showComparison() {
  $('comparison').hidden = !saved;
  if (!saved) return;
  $('saved-time').textContent = 'Saved · ' + new Date(saved.captured_at).toLocaleString();
  const left = comparisonRows(saved);
  const right = current ? comparisonRows(current) : [];
  for (const [i, row] of Array.from($('comparison').tBodies[0].rows).entries()) {
    row.cells[1].textContent = left[i];
    row.cells[2].textContent = right[i] ?? '—';
  }
}

function show(snapshot, unavailable) {
  const meta = snapshot?.controller;
  const motors = snapshot?.servos;
  const imu = snapshot?.imu;
  const state = meta?.feedback ?? 'offline';
  const connection = state === 'live' ? 'Controller feedback live'
    : state === 'stale' ? 'Controller feedback stale' : 'UNO Q unavailable';
  $('link-state').dataset.state = state;
  if ($('link-state').textContent !== connection) $('link-state').textContent = connection;
  $('export').disabled = !snapshot;
  const imuState = {online:'Fresh IMU data', offline:imu?.sample_sequence === 0 && imu.init_attempts > 0
    ? 'Offline · initialization is retrying' : 'IMU offline', stale:'Waiting for fresh controller feedback'};
  const readings = {
    rate:format(meta?.feedback_hz, 1, ' Hz'), age:format(meta?.feedback_age_ms, 1, ' ms'),
    torque:meta?.torque_enabled == null ? '—' : meta.torque_enabled ? 'On' : 'Off',
    misses:meta?.board_missed_slots ?? '—', overruns:meta?.mcu_overruns ?? '—',
    'servo-count':motors?.available ? `${motors.expected.length - motors.missing.length}/${motors.expected.length}` : '—',
    voltage:format(motors?.voltage_v, 2, ' V'),
    'servo-detected':motors?.available ? idList(motors.detected) : '—',
    'servo-missing':motors?.available ? idList(motors.missing) : '—',
    'servo-unexpected':motors?.unexpected.join(', ') ?? '',
    'imu-state':imu ? imuState[imu.state] : 'Waiting for feedback…',
    sequence:imu?.sample_sequence ?? '—', init:imu?.init_attempts ?? '—', errors:imu?.errors ?? '—',
    tilt:format(imu?.tilt_deg, 1, '°'), calibration:imu?.calibration_saved == null ? '—' : imu.calibration_saved ? 'Saved' : 'Pending',
    gravity:formatVector(imu?.gravity), acc:formatVector(imu?.raw_acc_ms2), gyro:formatVector(imu?.corrected_gyro_dps),
  };
  for (const [key, value] of Object.entries(readings)) $(key).textContent = value;
  $('unexpected-group').hidden = !motors?.unexpected.length;
  $('controller-error').textContent = meta?.error || unavailable || '';
  $('controller-error').hidden = !$('controller-error').textContent;
  showComparison();
}

async function poll() {
  if (polling || document.hidden) return;
  polling = true;
  try {
    const response = await fetch('/api/status', {cache:'no-store', signal:AbortSignal.timeout(2000)});
    if (!response.ok) throw new Error('Connect to the UNO Q to read controller telemetry.');
    current = benchSnapshot(await response.json(), release);
    show(current);
  } catch (error) {
    current = null;
    show(null, error.message);
  } finally { polling = false; }
}

function announce(text) {
  $('file-state').textContent = text;
  $('file-state').hidden = false;
}

$('export').addEventListener('click', () => {
  if (!current) return;
  const stamp = current.captured_at.replace(/[:.]/g, '-');
  downloadJson({...current, release:current.release ?? release}, `duck-lab-bench-${stamp}.json`);
  announce('Snapshot downloaded.');
});

$('import').addEventListener('change', async event => {
  const {target} = event;
  const [file] = target.files;
  if (!file) return;
  target.disabled = true;
  try {
    if (file.size > 32768) throw new Error('Choose a Bench diagnostics snapshot under 32 KiB.');
    saved = readBenchSnapshot(JSON.parse(await file.text()));
    showComparison();
    announce('Saved snapshot loaded.');
  } catch (error) {
    announce(error instanceof SyntaxError ? 'The file could not be read as JSON.' : error.message);
  } finally {
    target.value = '';
    target.disabled = false;
  }
});

poll();
setInterval(poll, 2000);
document.addEventListener('visibilitychange', poll);
