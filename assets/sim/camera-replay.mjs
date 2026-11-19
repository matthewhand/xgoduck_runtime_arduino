import {GroveCamera, CAPTURE_FORMAT, FRAME_LIMIT, MAX_FRAMES, jpegBytes, parseRecording} from './grove-capture.mjs';
import {dockReference} from './dock-localization.mjs';
import {compareDockFrame, differs, frameOutcome} from './dock-footage.mjs';

const $ = id => document.getElementById(id);
const canvas = $('frame'), view = canvas.getContext('2d');
const scratch = document.createElement('canvas');
const detail = scratch.getContext('2d', {willReadFrequently:true});
const nativeCanvas = document.createElement('canvas');
const native = nativeCanvas.getContext('2d', {willReadFrequently:true});
const pause = ms => new Promise(resolve => setTimeout(resolve,ms));
const serialReady = window.isSecureContext && Boolean(navigator.serial);
const methods = ['mlp','cad'];
const colours = {mlp:'#57e1ce',cad:'#c4a9ff',truth:'#ffcc69'};
let camera, working = false, recording = false, stopAfterFrame = false;
let frames = [], results = [], source = '', index = 0, timer = null, drawing = false, drag;
let models, picture, renderRequest = 0;

async function json(name) {
  const response = await fetch(new URL(name,import.meta.url),{signal:AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error(`Could not load ${name} (HTTP ${response.status}).`);
  return response.json();
}

function detectorModels() {
  models ??= Promise.all([json('dock-detector.json'),json('dock-vision-layout.json')])
    .then(([model,layout]) => ({model,reference:dockReference(layout)}))
    .catch(error => { models = null; throw error; });
  return models;
}

function limitSize(width,height) {
  const ratio = Math.min(1,FRAME_LIMIT/Math.max(width,height));
  return [Math.max(1,Math.round(width*ratio)),Math.max(1,Math.round(height*ratio))];
}

function asJpeg(input,width,height,x=0,y=0) {
  [scratch.width,scratch.height] = limitSize(width,height);
  detail.drawImage(input,x,y,width,height,0,0,scratch.width,scratch.height);
  return scratch.toDataURL('image/jpeg',.93).split(',')[1];
}

async function imageFor(frame) {
  return createImageBitmap(new Blob([jpegBytes(frame.jpeg)],{type:'image/jpeg'}));
}

function compareImage(image, {model,reference}) {
  const [w,h] = limitSize(image.width,image.height);
  scratch.width = w;
  scratch.height = h;
  detail.drawImage(image,0,0,w,h);
  const {width,height} = model;
  nativeCanvas.width = width;
  nativeCanvas.height = height;
  const scale = Math.min(width/w,height/h);
  const offset = [(width-w*scale)/2,(height-h*scale)/2];
  native.fillStyle = '#808080';
  native.fillRect(0,0,width,height);
  native.drawImage(scratch,...offset,w*scale,h*scale);
  return compareDockFrame(model,reference,native.getImageData(0,0,width,height),
    detail.getImageData(0,0,w,h),{scale,offset});
}

function reviewedFrames() {
  const filter = $('filter').value;
  return frames.flatMap((frame,i) => {
    const result = results[i];
    const outcomes = result ? methods.map(key => frameOutcome(frame,result[key])) : [];
    const show = filter === 'all' || (filter === 'unlabelled' && frame.truth === 'unknown') ||
      (filter === 'difference' && result && differs(result.mlp,result.cad)) ||
      outcomes.includes(filter) || (filter === 'miss' && outcomes.includes('wrong box'));
    return show ? [i] : [];
  });
}

function updateControls() {
  const frame = frames[index];
  $('connect').disabled = !serialReady || working || recording;
  $('connect').textContent = camera ? 'Disconnect Grove' : 'Connect Grove';
  $('record').disabled = !camera || working;
  $('record').textContent = recording ? 'Stop capture' : 'Record up to 20 s';
  for (const id of ['open','example','save','export']) $(id).disabled =
    working || recording || (id === 'save' && !frames.length) || (id === 'export' && !results.some(Boolean));
  $('truth').disabled = $('box').disabled = !frame || working || recording;
  $('clear-box').disabled = !frame?.box || working || recording;
  $('filter').disabled = !frames.length || working || recording;
}

function updateReview() {
  const indices = reviewedFrames();
  const position = indices.indexOf(index);
  const available = indices.length;
  $('seek').max = Math.max(0,available-1);
  $('seek').value = Math.max(0,position);
  $('previous').disabled = $('next').disabled = working || recording || !available || (available === 1 && position >= 0);
  $('play').disabled = $('seek').disabled = available < 2 || working || recording;
  $('review-status').textContent = frames.length
    ? `${available} of ${frames.length} frames in this view · ${frames.filter(f=>f.truth==='unknown').length} unlabelled` : '—';
  const rows = ['hit','miss','wrong box','false alarm','clear'];
  $('totals').replaceChildren(...rows.map(outcome => {
    const tr = document.createElement('tr');
    const counts = methods.map(key => results.reduce((sum,result,i) =>
      sum + Number(Boolean(result) && frameOutcome(frames[i],result[key]) === outcome),0));
    for (const [i,value] of [outcome,...counts].entries()) {
      const cell = document.createElement(i===0 ? 'th' : 'td');
      if (i === 0) cell.scope = 'row';
      cell.textContent = String(value);
      tr.append(cell);
    }
    return tr;
  }));
}

function boxOutline(box, colour, dashed = false) {
  if (!box) return;
  const [l,t,r,b] = box;
  view.strokeStyle = colour;
  view.lineWidth = Math.max(2,canvas.width/260);
  view.setLineDash(dashed ? [6,4] : []);
  view.strokeRect(l*canvas.width,t*canvas.height,(r-l)*canvas.width,(b-t)*canvas.height);
}

function repaint() {
  if (!picture) return;
  view.drawImage(picture,0,0,canvas.width,canvas.height);
  const result = results[index];
  for (const key of methods) boxOutline(result?.[key]?.bbox,colours[key]);
  boxOutline(frames[index].box,colours.truth,true);
  if (drag) boxOutline(dragBox(drag.start,drag.end),colours.truth,true);
}

async function show(i) {
  if (!frames[i]) return;
  index = i;
  const frame = frames[i], result = results[i];
  const request = ++renderRequest;
  $('truth').value = frame.truth;
  $('time').textContent = `#${i+1} · ${(frame.t/1000).toFixed(2)} s`;
  for (const key of methods) {
    const fit = result?.[key];
    const diagnosis = key === 'mlp' ? result?.mlpStage : 'no marker fit';
    const outcome = frameOutcome(frame,fit);
    $(key+'-frame').textContent = result
      ? [outcome==='unlabelled' ? null : outcome, fit?.ids.join(', ') || diagnosis,
          key==='mlp' ? `score ${result.mlpScore.toFixed(4)}` : fit && `residual ${fit.rms.toFixed(1)} px`,
          `${result[key+'Ms'].toFixed(1)} ms`].filter(Boolean).join(' · ') : 'Waiting for analysis';
  }
  $('frame-holder').hidden = $('transport').hidden = false;
  $('frame-caption').textContent = result && differs(result.mlp,result.cad)
    ? 'The detectors disagree on this frame.' : 'Draw a dock box to score localization at 50% overlap.';
  updateControls();
  updateReview();
  try {
    const bitmap = await imageFor(frame);
    if (request !== renderRequest) { bitmap.close(); return; }
    picture?.close();
    picture = bitmap;
    [canvas.width,canvas.height] = limitSize(bitmap.width,bitmap.height);
    canvas.style.maxWidth = `${65*canvas.width/canvas.height}vh`;
    repaint();
  } catch {
    if (request !== renderRequest) return;
    picture?.close();
    picture = null;
    view.clearRect(0,0,canvas.width,canvas.height);
    $('frame-caption').textContent = 'This JPEG could not be decoded.';
  }
}

function stopPlayback() {
  clearTimeout(timer);
  timer = null;
  $('play').textContent = 'Play';
}

function navigate(delta) {
  const indices = reviewedFrames();
  const at = indices.indexOf(index);
  return show(indices[at < 0 ? 0 : (at+delta+indices.length)%indices.length]);
}

function playNext() {
  const indices = reviewedFrames(), at = indices.indexOf(index);
  const next = indices[(at+1)%indices.length];
  const delay = next > index ? frames[next].t-frames[index].t : 750;
  timer = setTimeout(async () => {
    if (!document.hidden) await show(next);
    if (timer !== null) playNext();
  }, Math.min(2500,Math.max(100,delay)));
}

async function analyze(nextFrames, nextSource) {
  stopPlayback();
  frames = nextFrames;
  results = [];
  source = nextSource;
  $('filter').value = 'all';
  await show(0);
  const loaded = await detectorModels();
  let invalid = 0;
  for (const [i,frame] of frames.entries()) {
    $('camera-status').textContent = `${source} · Comparing frame ${i+1} / ${frames.length}…`;
    await pause(0);
    let bitmap;
    try { bitmap = await imageFor(frame); }
    catch { invalid++; continue; }
    try { results[i] = compareImage(bitmap,loaded); }
    finally { bitmap.close(); }
  }
  $('camera-status').textContent = `${source} · ${frames.length-invalid} frames analysed` +
    (invalid ? ` · ${invalid} unreadable JPEGs` : '');
  await show(0);
}

async function importVideo(file) {
  const player = document.createElement('video');
  player.muted = true;
  const url = URL.createObjectURL(file);
  function event(name) {
    return new Promise((resolve,reject) => {
      const timeout = setTimeout(() => done(new Error('Video did not decode or seek.')),6000);
      const success = () => done();
      const error = () => done(new Error('This browser could not decode the video.'));
      function done(failure) {
        clearTimeout(timeout);
        player.removeEventListener(name,success);
        player.removeEventListener('error',error);
        if (failure) reject(failure); else resolve();
      }
      player.addEventListener(name,success);
      player.addEventListener('error',error);
    });
  }
  try {
    const loaded = event('loadeddata');
    player.src = url;
    await loaded;
    if (!Number.isFinite(player.duration) || player.duration <= 0) throw new Error('Use a video file with a known duration.');
    const step = Math.max(.5,player.duration/MAX_FRAMES);
    const sampled = [];
    for (let i=0; i<MAX_FRAMES && i*step<player.duration; i++) {
      $('camera-status').textContent = `Reading video at ${(i*step).toFixed(1)} s…`;
      if (i) {
        const sought = event('seeked');
        player.currentTime = i*step;
        await sought;
      }
      sampled.push({t:i*step*1000,truth:'unknown',jpeg:asJpeg(player,player.videoWidth,player.videoHeight)});
    }
    return sampled;
  } finally {
    player.removeAttribute('src');
    player.load();
    URL.revokeObjectURL(url);
  }
}

async function loadFiles(files) {
  stopPlayback();
  const first = files[0];
  if (files.length===1 && /\.json$/i.test(first.name)) {
    if (first.size > 64*1024*1024) throw new Error('Choose a recording smaller than 64 MB.');
    const value = JSON.parse(await first.text());
    const provenance = typeof value.source === 'string' ? value.source.slice(0,180) : first.name;
    await analyze(parseRecording(value),provenance);
    return;
  }
  if (files.length===1 && (first.type.startsWith('video/') || /\.(mp4|webm|mov|m4v)$/i.test(first.name))) {
    await analyze(await importVideo(first),first.name);
    return;
  }
  if (files.length>MAX_FRAMES || files.some(file=>!/^image\/(jpeg|png)$/.test(file.type) && !/\.(jpe?g|png)$/i.test(file.name))) {
    throw new Error('Open one recording or video, or select up to 60 JPEG/PNG images.');
  }
  const stills = [];
  for (const [i,file] of files.entries()) {
    const bitmap = await createImageBitmap(file);
    try { stills.push({t:i*1000,truth:'unknown',jpeg:asJpeg(bitmap,bitmap.width,bitmap.height)}); }
    finally { bitmap.close(); }
  }
  await analyze(stills,files.length===1 ? first.name : 'Imported stills');
}

async function example() {
  const replay = await json('dock-survivors.json');
  const response = await fetch(new URL(replay.detail,import.meta.url),{signal:AbortSignal.timeout(12000)});
  if (!response.ok) throw new Error('The synthetic example image is unavailable.');
  const atlas = await createImageBitmap(await response.blob());
  const w = replay.width*replay.scale, h = replay.height*replay.scale;
  try {
    const examples = replay.frames.map((frame,i) => {
      const jpeg = asJpeg(atlas,w,h,(frame.tile%replay.columns)*w,Math.floor(frame.tile/replay.columns)*h);
      const truth = frame.bbox ? 'present' : 'absent';
      const labelled = {t:i*1000,truth,jpeg};
      if (frame.bbox) labelled.box = frame.bbox.map((v,j) => v/(j%2 ? replay.height : replay.width));
      return labelled;
    });
    await analyze(examples,'Synthetic dock scenes');
  } finally { atlas.close(); }
}

async function busy(task) {
  if (working || recording) return;
  working = true;
  updateControls();
  try { await task(); }
  catch (error) { $('camera-status').textContent = error.message; }
  finally { working = false; updateControls(); updateReview(); }
}

async function connect() {
  if (camera) {
    const previous = camera;
    camera = null;
    await previous.close();
    $('camera-status').textContent = 'Grove disconnected.';
    return;
  }
  const port = await navigator.serial.requestPort();
  const next = new GroveCamera(port);
  try { await next.open(); }
  catch (error) { await next.close().catch(()=>{}); throw error; }
  camera = next;
  $('camera-status').textContent = 'Grove serial port open. Start a recording to request camera frames.';
}

async function capture() {
  if (recording) { stopAfterFrame = true; return; }
  recording = true;
  stopAfterFrame = false;
  stopPlayback();
  updateControls();
  let error;
  const captured = [], start = performance.now(), deadline = start + 20000;
  $('camera-status').textContent = 'Requesting a Grove camera sample…';
  try {
    while (!stopAfterFrame && captured.length<MAX_FRAMES) {
      const remaining = deadline - performance.now();
      // Leave a full response window for each sample after the first.
      if (remaining < 6000 && captured.length) break;
      const jpeg = await camera.sample(Math.min(6000,remaining));
      captured.push({t:performance.now()-start,truth:'unknown',jpeg});
      $('camera-status').textContent = `Capturing Grove · ${captured.length} frames`;
      if (!stopAfterFrame) await pause(200);
    }
  } catch (failure) {
    error = failure;
    await camera.close().catch(()=>{});
    camera = null;
  } finally {
    recording = false;
    updateControls();
  }
  if (captured.length) await busy(() => analyze(captured,'Grove Vision AI V2'));
  if (error) $('camera-status').textContent += ` · ${error.message}`;
}

function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content],{type}));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
}

function exportResults() {
  const csv = ['frame,time_ms,truth,mlp_outcome,mlp_stage,mlp_score,mlp_ids,mlp_bbox,cad_outcome,cad_ids,cad_bbox,cad_residual_px,mlp_ms,cad_ms'];
  for (const [i,frame] of frames.entries()) {
    const result = results[i];
    if (!result) continue;
    csv.push([i+1,frame.t.toFixed(2),frame.truth,frameOutcome(frame,result.mlp),result.mlpStage,
      result.mlpScore,result.mlp?.ids.join('|'),result.mlp?.bbox.join('|'),frameOutcome(frame,result.cad),
      result.cad?.ids.join('|'),result.cad?.bbox.join('|'),result.cad?.rms,result.mlpMs,result.cadMs].join(','));
  }
  download('duck-lab-camera-results.csv',csv.join('\n'),'text/csv');
}

function pointerPosition(event) {
  const rect = canvas.getBoundingClientRect();
  return [(event.clientX-rect.left)/rect.width,(event.clientY-rect.top)/rect.height]
    .map(v=>Math.max(0,Math.min(1,v)));
}

function dragBox(a,b) {
  return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];
}

function setDrawing(active) {
  drawing = active;
  drag = null;
  $('frame-holder').classList.toggle('drawing',active);
  $('box').setAttribute('aria-pressed',String(active));
}

$('connect').onclick = () => void busy(connect);
$('record').onclick = () => void capture();
$('open').onclick = () => $('file').click();
$('file').onchange = event => {
  const files = [...event.target.files];
  event.target.value = '';
  if (files.length) void busy(() => loadFiles(files));
};
$('example').onclick = () => void busy(example);
$('save').onclick = () => download('duck-lab-camera.json',JSON.stringify({
  format:CAPTURE_FORMAT,source,frames,
}),'application/json');
$('export').onclick = exportResults;
$('previous').onclick = () => { stopPlayback(); void navigate(-1); };
$('next').onclick = () => { stopPlayback(); void navigate(1); };
$('play').onclick = () => {
  if (timer !== null) stopPlayback();
  else { setDrawing(false); $('play').textContent = 'Pause'; playNext(); }
};
$('seek').oninput = event => { stopPlayback(); setDrawing(false); void show(reviewedFrames()[Number(event.target.value)]); };
$('filter').onchange = () => {
  stopPlayback();
  setDrawing(false);
  const indices = reviewedFrames();
  if (indices.length) void show(indices[0]); else updateReview();
};
$('truth').onchange = event => {
  stopPlayback();
  frames[index].truth = event.target.value;
  if (event.target.value !== 'present') delete frames[index].box;
  void show(index);
};
$('box').onclick = () => { stopPlayback(); setDrawing(!drawing); repaint(); };
$('clear-box').onclick = () => { delete frames[index].box; void show(index); };
canvas.onpointerdown = event => {
  if (!drawing || !picture) return;
  const point = pointerPosition(event);
  drag = {start:point,end:point,frame:index};
  canvas.setPointerCapture(event.pointerId);
};
canvas.onpointermove = event => {
  if (!drag) return;
  drag.end = pointerPosition(event);
  repaint();
};
canvas.onpointerup = () => {
  if (!drag) return;
  const box = dragBox(drag.start,drag.end);
  if (drag.frame === index && box[2]-box[0]>.01 && box[3]-box[1]>.01) {
    frames[index].truth = 'present';
    frames[index].box = box;
  }
  setDrawing(false);
  void show(index);
};
canvas.onpointercancel = () => { setDrawing(false); repaint(); };
window.addEventListener('pagehide', () => {
  stopPlayback();
  stopAfterFrame = true;
  void camera?.close().catch(()=>{});
});
if (!serialReady) $('camera-status').textContent =
  'Open footage here, or use Duck Lab on localhost or HTTPS in Chrome or Edge to capture over USB.';
updateControls();
