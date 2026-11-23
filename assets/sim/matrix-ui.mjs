const $ = id => document.getElementById(id);

function attachMatrixControls(shouldPoll) {
  const next = $('matrix-next'), automatic = $('matrix-auto'), note = $('matrix-note');
  let enabled = false, connected = false, pending = false;
  async function request(body) {
    if (pending) return;
    pending = true;
    next.disabled = automatic.disabled = true;
    const options = {cache:'no-store', signal:AbortSignal.timeout(1800)};
    if (body) Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)});
    try {
      const response = await fetch('/api/matrix', options);
      if (!response.ok) throw new Error('Matrix controls unavailable.');
      const state = await response.json();
      enabled = state.auto === true;
      connected = true;
      note.textContent = body?.action === 'next' ? 'Tap within 3 s: CPU → GPU → RAM → TMP → art.' : '';
    } catch {
      connected = false;
      note.textContent = 'Matrix readouts unavailable. Retrying…';
    } finally {
      pending = false;
      automatic.checked = enabled;
      next.disabled = automatic.disabled = !connected;
    }
  }
  next.addEventListener('click', () => request({action:'next'}));
  automatic.addEventListener('change', () => request({action:'auto', enabled:automatic.checked}));
  async function poll() {
    if (!shouldPoll()) return;
    if (!document.hidden && !connected && !pending) await request();
    if (shouldPoll()) setTimeout(poll, 1800);
  }
  poll();
}

function attachMatrixPlayer(shouldPoll) {
  const picker = $('matrix-scenes'), play = $('matrix-play'), skip = $('matrix-skip');
  const playing = $('matrix-playing'), error = $('matrix-scene-error');
  let requestId = 0, pending = false, available = false, catalog = null, noticeFrom = Infinity;

  function updateButtons() {
    picker.disabled = skip.disabled = pending || !available;
    play.disabled = pending || !available || picker.value === '';
    play.textContent = picker.value !== '' && Number(picker.value) >= noticeFrom ? 'Show once' : 'Play';
  }

  async function request(body) {
    const id = ++requestId;
    if (body) {
      pending = true;
      updateButtons();
    }
    const options = {cache:'no-store', signal:AbortSignal.timeout(1800)};
    if (body) Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)});
    try {
      const response = await fetch('/api/matrix/scene', options);
      if (!response.ok) throw new Error('Scene controls unavailable.');
      const {scenes, current, encore_from: encoreFrom, marquee_from: marqueeFrom = scenes.length} = await response.json();
      if (id !== requestId) return;
      noticeFrom = marqueeFrom;
      const key = JSON.stringify([scenes, encoreFrom, marqueeFrom]);
      if (catalog !== key) {
        const selection = picker.value;
        picker.replaceChildren(new Option('Choose animation', ''));
        for (const [label, start, end] of [
          ['Notifications', marqueeFrom, scenes.length],
          ['New scenes', encoreFrom, marqueeFrom],
          ['Earlier scenes', 0, encoreFrom],
        ]) {
          if (start === end) continue;
          const group = document.createElement('optgroup');
          group.label = label;
          for (let i = start; i < end; i++) group.append(new Option(scenes[i], String(i)));
          picker.append(group);
        }
        picker.value = selection;
        catalog = key;
      }
      playing.textContent = `${current >= noticeFrom ? 'Notification' : 'Now playing'} · ${scenes[current]}`;
      error.hidden = true;
      available = true;
    } catch {
      if (id !== requestId) return;
      playing.textContent = 'Board unavailable';
      error.textContent = 'Could not reach the scene controls. Retrying…';
      error.hidden = false;
      available = false;
    } finally {
      if (id === requestId) {
        pending = false;
        updateButtons();
      }
    }
  }

  picker.addEventListener('change', updateButtons);
  play.addEventListener('click', () => request({index:Number(picker.value)}));
  skip.addEventListener('click', () => request({action:'skip'}));
  async function poll() {
    if (!document.hidden && !pending) await request();
    if (shouldPoll()) setTimeout(poll, 1800);
  }
  poll();
}

export function mountMatrixControls(shouldPoll = () => true) {
  attachMatrixControls(shouldPoll);
  attachMatrixPlayer(shouldPoll);
}
