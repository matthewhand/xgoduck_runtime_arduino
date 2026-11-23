import {mountMatrixControls} from './matrix-ui.mjs?v=2';
import {mountTrialExport, readChecklist, readRelease, saveChecklist} from './trial-report.mjs?v=2';

const boardUrl = new URL(location.href);
const isLocal = ['localhost', '127.0.0.1', '[::1]'].includes(boardUrl.hostname);
if (!isLocal) {
  const rebootUrl = new URL('/', boardUrl);
  rebootUrl.protocol = 'http:';
  rebootUrl.port = '9528';
  const reboot = document.getElementById('wifi-reboot');
  reboot.href = rebootUrl.href;
  reboot.hidden = false;
} else {
  document.getElementById('wifi-reboot-note').hidden = false;
}
mountMatrixControls();

const checklist = [...document.querySelectorAll('#build-checklist input')];
const count = document.getElementById('checklist-count');
const storageNote = document.getElementById('checklist-storage');
const boardNote = document.getElementById('checklist-board');
const trialNote = document.getElementById('build-trial-state');
const setExportRun = mountTrialExport(document.getElementById('build-export'),
  document.getElementById('build-export-result'));
const physicalNote = document.getElementById('build-physical-state');
const setPhysicalExport = mountTrialExport(document.getElementById('build-physical-export'),
  document.getElementById('build-physical-export-result'), '/api/lab/physical/report');
const comparison = document.getElementById('trial-comparison');
let comparedRuns = '';
let records = readChecklist();

function showChecklist() {
  for (const box of checklist) box.checked = Boolean(records[box.value]);
  count.textContent = `${checklist.filter(box => box.checked).length} of ${checklist.length} checked`;
}

showChecklist();
readRelease().then(release => {
  for (const box of checklist) {
    box.disabled = false;
    box.addEventListener('change', () => {
      if (box.checked) records[box.value] = {
        checked_at: new Date().toISOString(), release: release?.commit ?? null,
      };
      else delete records[box.value];
      try {
        saveChecklist(records);
        storageNote.hidden = true;
      } catch {
        storageNote.hidden = false;
        storageNote.textContent = 'This browser could not save checklist progress.';
      }
      showChecklist();
    });
  }
});

async function getStatus(path) {
  try {
    const response = await fetch(path, {cache:'no-store', signal:AbortSignal.timeout(2000)});
    return response.ok ? await response.json() : null;
  } catch { return null; }
}

async function showComparison(simKey, physicalKey) {
  if (!simKey || !physicalKey) {
    comparison.hidden = true;
    comparedRuns = '';
    return;
  }
  const key = `${simKey}/${physicalKey}`;
  if (comparedRuns === key) return;
  comparison.hidden = true;
  const [sim, physical] = await Promise.all([getStatus('/api/lab/walk/report'), getStatus('/api/lab/physical/report')]);
  if (sim?.run_key !== simKey || physical?.run_key !== physicalKey) return;
  comparedRuns = key;
  if (sim.pond || sim.arena || physical.state !== 'complete') return;

  const fmt = (value, digits, unit = '') => Number.isFinite(value) ? value.toFixed(digits) + unit : '—';
  const metrics = {
    duration: trial => fmt(trial.time_s, 1, ' s'),
    cpu: trial => fmt(trial.load_peaks?.cpu_percent, 1, '%'),
    gpu: trial => fmt(trial.load_peaks?.gpu_percent, 1, '%'),
    missed: trial => fmt(trial.board_missed_slots, 0),
    recovery: trial => fmt(trial.recoveries?.find(event => event.fall_to_walk_s != null)?.fall_to_walk_s, 2, ' s'),
  };
  for (const row of comparison.querySelectorAll('tbody tr')) {
    row.cells[1].textContent = metrics[row.dataset.metric](sim);
    row.cells[2].textContent = metrics[row.dataset.metric](physical);
  }
  comparison.hidden = false;
}

async function pollBuildStatus() {
  if (document.hidden) return;
  const [board, trial, physical] = await Promise.all([
    getStatus('/api/status'), getStatus('/api/lab/walk'), getStatus('/api/lab/physical'),
  ]);
  if (Array.isArray(board?.servo_ids) && Number.isFinite(board.feedback_age_ms) && board.feedback_age_ms < 150) {
    const expected = board.motors?.length || 15;
    boardNote.textContent = `Board now · ${board.servo_ids.length}/${expected} servos · IMU ${board.imu_ok ? 'online' : 'offline'}`;
  } else boardNote.textContent = 'Fresh servo and IMU feedback unavailable.';

  setExportRun(trial?.report_run_key ?? null);
  trialNote.textContent = trial?.report_run_key ? 'JSON includes board load samples, missed slots and recovery events.'
    : trial?.available ? 'Run a live simulation to record load, missed slots and recovery.'
    : 'Connect to the UNO Q to export a live simulation.';
  setPhysicalExport(physical?.report_run_key ?? null);
  physicalNote.textContent = physical?.recording ? 'Physical capture in progress.'
    : physical?.report_run_key ? 'The latest physical capture is ready to export.'
    : physical?.blocked || (physical ? 'Ready for a physical capture.' : 'Connect to the UNO Q for physical capture.');
  await showComparison(trial?.report_run_key, physical?.report_run_key);
}

pollBuildStatus();
setInterval(pollBuildStatus, 3500);
