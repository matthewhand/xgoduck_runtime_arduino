const api = '/api/triple-m';
const published = './triple-m-report.json';
const request = options => ({signal:AbortSignal.timeout(45000), ...options});

export const batchUrl = (id, file) => `${api}/batches/${encodeURIComponent(id)}/${file}`;
export const reportUrl = report => report.source === 'runner'
  ? batchUrl(report.id, 'report') : report.source === 'legacy' ? `${api}/report` : new URL(published, import.meta.url).href;

export async function tripleJson(path, options) {
  const response = await fetch(new URL(path, import.meta.url), request(options));
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    const error = new Error(detail?.error ?? detail?.message ?? `Request failed (HTTP ${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

export const runnerStatus = () => tripleJson(`${api}/status`, {cache:'no-store', signal:AbortSignal.timeout(5000)});

export function caseState(row) {
  if (row.state) return row.state;
  if (!row.result) return 'pending';
  return row.result.skipped ? 'skipped' : row.result.passed ? 'passed' : 'failed';
}

export function replayable(row) {
  return ['passed','failed','skipped'].includes(caseState(row)) && Boolean(row.result);
}

export function reportSummary(report) {
  return {
    ...report,
    cases:report.cases.map(row => {
      const {trace, ...result} = row.result ?? {};
      return {...row, result:row.result ? result : null};
    }),
  };
}

export async function openTripleReport({local = false, id} = {}) {
  if (local) {
    if (!id) {
      const status = await runnerStatus();
      id = status.report_id;
    }
    if (id) {
      const summary = await tripleJson(batchUrl(id, 'summary'), {cache:'no-store'});
      return {
        ...summary, id, source:'runner',
        load: key => tripleJson(batchUrl(id, `cases/${encodeURIComponent(key)}`)),
      };
    }
    const report = await tripleJson(`${api}/report`, {cache:'no-store'});
    return {...reportSummary(report), source:'legacy', load: key => report.cases.find(row => row.key === key)};
  }

  try {
    if (id && !/^[a-f0-9]{64}$/.test(id)) throw new Error('Invalid published report ID.');
    const index = id ? `./triple-m-index-${id}.json` : './triple-m-index.json';
    const summary = await tripleJson(index, id ? undefined : {cache:'no-cache'});
    if (!/^[a-f0-9]{64}$/.test(summary.id) || (id && id !== summary.id)) {
      throw new Error('The published report does not match its index.');
    }
    return {
      ...summary, source:'published',
      load:key => tripleJson(`./triple-m-case-${summary.id}-${encodeURIComponent(key)}.json`),
    };
  } catch (error) {
    if (error.status !== 404) throw error;
    if (id) throw new Error('This published report is unavailable here.');
    const report = await tripleJson(published);
    return {...reportSummary(report), source:'published', load:key => report.cases.find(row => row.key === key)};
  }
}

export function replayLink(report, row) {
  const params = new URLSearchParams({triple:'1'});
  if (report.source !== 'published') params.set('source', 'local');
  if (report.id) params.set('report', report.id);
  if (row) {
    params.set('all', '1');
    params.set('case', row.key);
  }
  return `simulate.html?${params}`;
}

export function panelLink(report) {
  const params = new URLSearchParams();
  if (report.source !== 'published') params.set('source', 'local');
  if (report.id) params.set('report', report.id);
  return params.size ? `triple-m.html?${params}` : 'triple-m.html';
}

export function matchingCase(rows, selected) {
  const setup = row => {
    const {build, modules, ...conditions} = row.case;
    return JSON.stringify(conditions);
  };
  const conditions = setup(selected);
  return rows.find(row => row.case.build !== selected.case.build && setup(row) === conditions);
}

export function tripleTrial(row) {
  const spec = row.case;
  return {
    ...row.result, modules:spec.modules,
    triple:{
      key:row.key, label:row.label, fault:spec.fault, skates:spec.move === 'skate',
      lane:['walk','skate'].includes(spec.move), scenario:spec.scenario,
    },
  };
}

export function incidentWindow(result, duration) {
  const events = Array.isArray(result.events) ? result.events : [];
  let anchor = events.find(event => event?.id === 'first-failure')?.time_s ?? result.failed_at_s;
  if (!Number.isFinite(anchor)) {
    if (result.failure) anchor = duration;
    else if (result.triple?.scenario) {
      const metrics = result.scenario_metrics;
      anchor = metrics?.jam_at_s ?? metrics?.shove_at_s ?? metrics?.gate_at_s
        ?? events.find(event => event?.id === 'gate-missed')?.time_s;
    } else anchor = result.triple?.fault?.at_s;
  }
  return Number.isFinite(anchor)
    ? {start: Math.max(0, anchor - 2), end: Math.min(duration, anchor + 3), anchor} : null;
}
