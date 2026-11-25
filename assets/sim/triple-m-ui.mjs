const $ = id => document.getElementById(id);
const form = $('batch-form');
const localOrigin = 'http://127.0.0.1:19534';
const local = location.origin === localOrigin;
const api = '/api/triple-m';
let report, localReport = false;

function options() {
  const fields = new FormData(form);
  return Object.fromEntries(['moves','builds','faults','grip','shove_m_s','jam_s','pack_g'].map(name =>
    [name, ['moves','builds','faults'].includes(name) ? fields.getAll(name) : Number(fields.get(name))]));
}

function updatePlan() {
  const plan = options();
  const nominal = Number(plan.faults.includes('nominal'));
  const moving = plan.moves.filter(move => move === 'walk' || move === 'skate').length;
  const count = plan.builds.length * (nominal * (plan.moves.length + 3*Number(plan.moves.includes('getup')))
    + 2*moving*Number(plan.faults.includes('shove')) + 2*Number(plan.moves.includes('skate') && plan.faults.includes('jam')));
  $('batch-plan').textContent = `${count} ${count === 1 ? 'case' : 'cases'}`;
  $('run-batch').disabled = !count || !form.checkValidity();
  $('save-plan').disabled = $('run-batch').disabled;
  $('local-runner').href = `${localOrigin}/triple-m.html?plan=${encodeURIComponent(JSON.stringify(plan))}`;
}

function replayLink(tag) {
  const params = new URLSearchParams({triple:'1'});
  if (localReport) params.set('source', 'local');
  if (tag) { params.set('all', '1'); params.set('case', tag); }
  return `simulate.html?${params}`;
}

function render() {
  const failures = report.cases.filter(row => !row.result.passed);
  const {ran, reused, workers} = report.compute;
  $('batch-summary').textContent = `${report.cases.length - failures.length} passed · ${failures.length} failed · ${ran} simulated · ${reused} reused · ${workers} CPU workers`;
  $('loop-failures').href = replayLink();
  $('loop-failures').hidden = !failures.length;
  $('batch-download').href = localReport ? `${api}/report` : 'sim/triple-m-report.json';
  $('batch-download').download = 'triple-m-report.json';
  const visible = $('failures-only').checked ? failures : report.cases;
  $('batch-list').replaceChildren(...visible.map(row => {
    const item = document.createElement('li');
    const info = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = row.label;
    const result = document.createElement('small');
    result.className = row.result.passed ? 'passed' : 'failed';
    result.textContent = row.result.failure ?? 'Passed';
    info.append(title, result);
    const link = document.createElement('a');
    link.href = replayLink(row.label);
    link.textContent = 'Replay';
    link.setAttribute('aria-label', `Replay ${row.label}`);
    item.append(info, link);
    return item;
  }));
}

async function json(url, request) {
  const response = await fetch(url, request);
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  return response.json();
}

async function refresh() {
  if (local) {
    const status = await json(`${api}/status`);
    if (status.state === 'running') {
      $('batch-status').textContent = status.total ? `${status.completed} / ${status.total} complete · ${status.reused} from cache` : 'Starting batch…';
      setTimeout(() => void refresh().catch(showError), 600);
      return;
    }
    if (status.has_report) {
      report = await json(`${api}/report`);
      localReport = true;
    }
    $('batch-status').textContent = status.state === 'error' ? status.message : 'Runs on this computer. Results are cached per case.';
    $('run-batch').hidden = false;
    form.inert = false;
  } else {
    $('batch-status').textContent = 'This page shows the published batch. Open the PC runner to run a new one.';
  }
  report ??= await json('sim/triple-m-report.json');
  render();
  updatePlan();
}

function showError(error) {
  $('batch-status').textContent = error.message;
  form.inert = false;
}

const provided = new URLSearchParams(location.search).get('plan');
if (provided) {
  try {
    const plan = JSON.parse(provided);
    for (const field of form.elements) {
      const value = plan[field.name];
      if (field instanceof HTMLInputElement && field.type === 'checkbox' && Array.isArray(value)) field.checked = value.includes(field.value);
      if (field instanceof HTMLInputElement && field.type === 'number' && Number.isFinite(value)) field.value = value;
    }
  } catch { /* Keep the defaults for an unreadable shared plan. */ }
}
$('local-runner').hidden = local;
form.addEventListener('input', updatePlan);
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!local || $('run-batch').disabled || form.inert) return;
  const plan = options();
  form.inert = true;
  $('batch-status').textContent = 'Starting batch…';
  try {
    await json(`${api}/run`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(plan)});
    await refresh();
  } catch (error) { showError(error); }
});
$('save-plan').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(options(), null, 2)+'\n'], {type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'triple-m-plan.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('failures-only').addEventListener('change', () => { if (report) render(); });
updatePlan();
void refresh().catch(showError);
