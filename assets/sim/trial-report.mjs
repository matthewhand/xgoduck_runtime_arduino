const checklistKey = 'duck-lab-build-checklist-v1';

export function readChecklist() {
  try {
    const record = JSON.parse(localStorage.getItem(checklistKey));
    return record && typeof record === 'object' && !Array.isArray(record) ? record : {};
  } catch { return {}; }
}

export function saveChecklist(record) {
  localStorage.setItem(checklistKey, JSON.stringify(record));
}

let releaseRequest;
export function readRelease() {
  releaseRequest ??= fetch(new URL('../build-test-release.json', import.meta.url), {
    cache:'no-store', signal:AbortSignal.timeout(2000),
  }).then(response => response.ok ? response.json() : null).catch(() => null);
  return releaseRequest;
}

export function downloadJson(payload, filename) {
  const file = new Blob([JSON.stringify(payload, null, 2) + '\n'], {type:'application/json'});
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

export function mountTrialExport(button, message, endpoint = '/api/lab/walk/report') {
  let runKey = null, exporting = false;
  const refresh = () => { button.disabled = !runKey || exporting; };
  button.addEventListener('click', async () => {
    if (!runKey || exporting) return;
    const expected = runKey;
    exporting = true;
    message.textContent = 'Downloading trial report…';
    refresh();
    try {
      const response = await fetch(endpoint, {cache:'no-store', signal:AbortSignal.timeout(5000)});
      if (!response.ok) throw new Error('The UNO Q did not return a trial report.');
      const trial = await response.json();
      if (trial?.run_key !== expected) throw new Error('The latest trial changed. Select export again.');
      const payload = {...trial, build_checklist:readChecklist()};
      const filename = trial.source === 'physical-duck' ? `duck-lab-physical-${trial.run_id}.json`
        : `duck-lab-trial-${trial.run_id}-${trial.run_key.slice(0,8)}.json`;
      downloadJson(payload, filename);
      message.textContent = `Downloaded trial ${trial.run_id}.`;
    } catch (error) { message.textContent = error.message; }
    finally { exporting = false; refresh(); }
  });
  return key => { runKey = key; refresh(); };
}
