import {batchUrl, caseState, openTripleReport, replayLink, replayable, reportUrl, runnerStatus, tripleJson} from './triple-m-replay.mjs?v=1';

const $ = id => document.getElementById(id);
const form = $('batch-form');
const fields = $('batch-fields');
const localOrigin = 'http://127.0.0.1:19534';
const api = '/api/triple-m';
const presetCoverage = {
  'wheel-jam-release': {count:6, label:'Skate, jam and release · both wheels, three responses'},
  'fall-recovery': {count:2, label:'Walk and recover · back and right-side falls'},
};
const movementLabels = {
  walk:'Walking', getup:'Get-up', skate:'Skating', dance:'Head dance',
  'polite-bow':'Polite bow', 'flamingo-cycle':'Flamingo',
};
const faultLabels = {nominal:'Baseline', shove:'Side shoves', jam:'Front-wheel jams'};
const query = new URLSearchParams(location.search);
const pinned = query.get('report');
let report, latestPublishedId, local = false, busy = false, poll, previousList;
const showText = (id, value) => { if ($(id).textContent !== value) $(id).textContent = value; };

function options() {
  const data = new FormData(form);
  const names = ['moves','builds','faults','scenarios','grip','shove_m_s','jam_s','pack_g'];
  const plan = Object.fromEntries(names.map(name => [name,
    ['moves','builds','faults','scenarios'].includes(name) ? data.getAll(name) : Number(data.get(name))]));
  if (!$('atomic-tests').checked) plan.moves = [];
  if (!plan.moves.length && !plan.faults.length) plan.faults = ['nominal','shove','jam'];
  return plan;
}

function updatePlan() {
  if (busy) return;
  const plan = options();
  const atomic = $('atomic-tests').checked;
  $('move-controls').hidden = $('fault-controls').hidden = !atomic;
  const entries = [];
  let count = 0;
  let skipped = 0;
  const record = (label, cases, reason) => {
    const total = cases * plan.builds.length;
    count += total;
    if (reason) skipped++;
    const item = document.createElement('li');
    item.textContent = reason
      ? `${label} · skipped. ${reason}`
      : `${label} · ${total} ${total === 1 ? 'case' : 'cases'}`;
    entries.push(item);
  };
  for (const move of plan.moves) {
    for (const fault of plan.faults) {
      const label = `${movementLabels[move]} · ${faultLabels[fault]}`;
      if (fault === 'nominal') record(label, move === 'getup' ? 4 : 1);
      if (fault === 'shove') {
        const supported = ['walk','skate'].includes(move);
        record(label, supported ? 2 : 0, supported ? '' : 'Requires walking or skating.');
      }
      if (fault === 'jam') {
        record(label, move === 'skate' ? 2 : 0, move === 'skate' ? '' : 'Requires skates.');
      }
    }
  }
  for (const preset of plan.scenarios) {
    const {label, count:cases} = presetCoverage[preset];
    record(label, cases);
  }
  if (!entries.length || !plan.builds.length) {
    const hint = document.createElement('li');
    hint.textContent = plan.builds.length
      ? 'Choose a movement and modifier, or choose a scenario preset.'
      : 'Choose at least one build.';
    entries.unshift(hint);
  }
  $('batch-plan').textContent = `Test coverage · ${count} ${count === 1 ? 'case' : 'cases'}${skipped ? ` · ${skipped} combinations skipped` : ''}`;
  $('batch-coverage').replaceChildren(...entries);
  const valid = count > 0 && form.checkValidity() && (!plan.moves.length || plan.faults.length > 0);
  $('run-batch').disabled = !valid;
  $('save-plan').disabled = !valid;
  $('local-runner').href = `${localOrigin}/triple-m.html?plan=${encodeURIComponent(JSON.stringify(plan))}`;
}

function applyPlan(plan) {
  if (!plan || typeof plan !== 'object' || Array.isArray(plan)) throw new Error('Choose a Triple M plan.');
  if (!Array.isArray(plan.moves) || !Array.isArray(plan.builds) || !Array.isArray(plan.faults)) {
    throw new Error('The plan is missing movements, builds or modifiers.');
  }
  $('atomic-tests').checked = plan.moves.length > 0;
  for (const field of form.elements) {
    if (!(field instanceof HTMLInputElement) || !field.name) continue;
    const value = plan[field.name];
    if (field.type === 'checkbox') field.checked = Array.isArray(value) && value.includes(field.value);
    if (field.type === 'number' && Number.isFinite(value)) field.value = value;
  }
  updatePlan();
}

function render() {
  if (!report) return;
  const failures = report.cases.filter(row => caseState(row) === 'failed');
  const counts = {};
  for (const row of report.cases) {
    const state = caseState(row);
    counts[state] = (counts[state] ?? 0) + 1;
  }
  const {ran = 0, reused = 0, workers = 0} = report.compute ?? {};
  const source = report.source === 'published' ? 'Published batch' : 'This PC';
  const date = report.created_at ? new Date(report.created_at).toLocaleString() : '';
  const state = {pending:'Queued',running:'In progress',partial:'Finished with runner errors',error:'Runner error'};
  $('batch-source').textContent = [source, date, state[report.state]].filter(Boolean).join(' · ');
  const summary = [`${counts.passed ?? 0} passed`, `${failures.length} failed`];
  for (const [key, text] of [['skipped','skipped'],['error','runner errors'],['pending','pending']]) {
    if (counts[key]) summary.push(`${counts[key]} ${text}`);
  }
  summary.push(`${ran} simulated`, `${reused} reused`, `${workers} CPU workers`);
  showText('batch-summary', summary.join(' · '));
  $('loop-failures').href = replayLink(report);
  $('loop-failures').hidden = !failures.length;
  $('batch-download').href = reportUrl(report);
  $('batch-download').hidden = report.state === 'pending' || report.state === 'running'
    || (report.source === 'published' && pinned && latestPublishedId !== report.id);
  $('retry-cases').hidden = report.source !== 'runner' || !['partial','error','pending'].includes(report.state) || busy;
  $('retry-cases').disabled = busy;
  const visible = $('failures-only').checked
    ? report.cases.filter(row => ['failed','error','skipped'].includes(caseState(row))) : report.cases;
  const list = JSON.stringify([report.source, report.id, visible.map(row =>
    [row.key, caseState(row), row.result?.failure, row.result?.skip_reason, row.error])]);
  if (list === previousList) return;
  previousList = list;
  $('batch-list').replaceChildren(...visible.map(row => {
    const item = document.createElement('li');
    const info = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = row.label;
    const state = caseState(row);
    const result = document.createElement('small');
    result.className = state;
    result.textContent = {
      passed:'Passed', failed:row.result?.failure ?? 'Failed',
      skipped:`Skipped · ${row.result?.skip_reason ?? 'Condition was not exercised.'}`,
      error:`Runner error · ${row.error ?? 'No recording was produced.'}`, pending:'Pending',
    }[state];
    info.append(title, result);
    item.append(info);
    if (replayable(row)) {
      const link = document.createElement('a');
      link.href = replayLink(report, row);
      link.textContent = 'Replay';
      link.setAttribute('aria-label', `Replay ${row.label}`);
      item.append(link);
    }
    return item;
  }));
}

function working(active) {
  busy = fields.disabled = $('retry-cases').disabled = active;
  if (!active) updatePlan();
}

async function refresh(status) {
  status ??= await runnerStatus();
  const running = status.state === 'running';
  working(running);
  if (running) {
    showText('batch-status', status.total
      ? `${status.completed} / ${status.total} complete · ${status.reused} reused`
      : 'Starting batch…');
    clearTimeout(poll);
    poll = setTimeout(() => void refresh().catch(showError), 800);
  } else {
    $('batch-status').textContent = status.state === 'error' || status.state === 'partial'
      ? status.message ?? 'One or more cases could not run.'
      : 'Batch runs on this computer’s CPU.';
  }

  const id = pinned ?? status.batch_id ?? status.report_id;
  if (id) report = await openTripleReport({local:true, id});
  else if (status.has_report) report = await openTripleReport({local:true});
  else report ??= await openTripleReport();
  render();
}

function showError(error) {
  clearTimeout(poll);
  $('batch-status').textContent = error.message;
  working(false);
}

async function start() {
  let status;
  try { status = await runnerStatus(); }
  catch { /* The board and older static hosts have no CPU runner endpoint. */ }
  local = status?.local === true;
  $('run-batch').hidden = !local || Boolean(pinned);
  $('latest-results').hidden = !pinned;
  if (pinned && query.get('source') === 'local') {
    if (!local) throw new Error('Open this replay on the PC that holds its recordings.');
    $('batch-status').textContent = 'Viewing the selected batch.';
    report = await openTripleReport({local:true, id:pinned});
    render();
    return;
  }
  if (local && !pinned) return refresh(status);
  $('batch-status').textContent = 'Published results are available here. Run new batches on a PC.';
  $('runner-help').hidden = false;
  $('local-runner').hidden = Boolean(navigator.userAgentData?.mobile || matchMedia('(pointer:coarse)').matches);
  report = await openTripleReport({id:pinned});
  if (pinned) latestPublishedId = (await openTripleReport().catch(() => ({}))).id;
  render();
}

async function submit(path, body) {
  clearTimeout(poll);
  working(true);
  $('batch-status').textContent = 'Starting batch…';
  try {
    await tripleJson(path, {
      method:'POST', ...(body ? {headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {}),
    });
    await refresh();
  } catch (error) {
    showError(error);
  }
}

const provided = new URLSearchParams(location.search).get('plan');
if (provided) {
  try { applyPlan(JSON.parse(provided)); }
  catch (error) { showError(error); }
}
form.addEventListener('input', updatePlan);
form.addEventListener('submit', event => {
  event.preventDefault();
  if (local && !pinned && !$('run-batch').disabled && !busy) void submit(`${api}/run`, options());
});
$('retry-cases').addEventListener('click', () => {
  if (!busy && report?.source === 'runner') void submit(batchUrl(report.id, 'retry'));
});
$('save-plan').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(options(), null, 2)+'\n'], {type:'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'triple-m-plan.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('open-plan').addEventListener('click', () => $('plan-file').click());
$('plan-file').addEventListener('change', async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  try {
    if (file.size > 64 * 1024) throw new Error('Choose a plan smaller than 64 KB.');
    applyPlan(JSON.parse(await file.text()));
    $('batch-status').textContent = `Opened ${file.name}.`;
  } catch (error) {
    showError(error instanceof SyntaxError ? new Error('The file is not a valid JSON plan.') : error);
  }
});
$('failures-only').addEventListener('change', render);
updatePlan();
void start().catch(showError);
