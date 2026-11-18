import {dockFaces, renderDockView} from './dock-vision-camera.mjs';
import {detectDock} from './dock-inference.mjs';
import {hasMarkerContrast} from './dock-marker.mjs';

import {markerCodebook, readDockPattern, detailCrop} from './dock-pattern.mjs';

const element = id => document.getElementById('vision-' + id);
const conditionNames = {
  orbit: 'Live 3D orbit',
  survivors: 'Eight contrast false alarms',
  'pattern-examples': 'Marked trial examples',
  marked: 'Marked dock',
  hidden: 'Dock with markers hidden',
  occluded: 'Partly obscured dock',
  full: 'Fully obscured dock',
  decoy: 'Look-alike object',
  empty: 'Empty scene',
};
const controls = ['condition', 'frame', 'prev', 'next', 'play'];
const display = element('pixels');
const context = display.getContext('2d', {willReadFrequently: true});
const query = new URLSearchParams(location.search);
let model, views, sprite, faces, codes, groups, frames, frame, prediction;
let replay, replaySprite, detailSprite;
const sensor = document.createElement('canvas');
const sensorContext = sensor.getContext('2d', {willReadFrequently:true});
const isOrbit = () => element('condition').value === 'orbit';
let index = 0, timer = null;

async function json(file) {
  const response = await fetch(new URL(file, import.meta.url));
  if (!response.ok) throw new Error(`Could not load ${file} (HTTP ${response.status})`);
  return response.json();
}

function loadSprite(file) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('Could not load the camera views'));
    image.src = new URL(file, import.meta.url).href;
  });
}

function overlap(a, b) {
  const area = box => Math.max(0, box[2] - box[0]) * Math.max(0, box[3] - box[1]);
  const intersection = area([Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.min(a[2], b[2]), Math.min(a[3], b[3])]);
  return intersection / Math.max(1e-9, area(a) + area(b) - intersection);
}

function showBox(name, box) {
  const rect = element(name);
  rect.toggleAttribute('hidden', !box);
  if (box) {
    rect.setAttribute('x', box[0]);
    rect.setAttribute('y', box[1]);
    rect.setAttribute('width', Math.max(0, box[2] - box[0]));
    rect.setAttribute('height', Math.max(0, box[3] - box[1]));
  }
}

function drawOverlay() {
  const showTruth = element('truth').checked;
  const method = element('verification').value;
  const wantsPattern = method === 'pattern' || method === 'detail';
  const requireContrast = method !== 'raw';
  let tag = prediction.tag;
  let resolution = '96 × 72';
  if (method === 'detail' && !tag && prediction.markerContrast && hasDetail()) {
    if (prediction.detailTag === undefined) prediction.detailTag = readDetail();
    tag = prediction.detailTag;
    resolution = `${model.width*replay.scale} × ${model.height*replay.scale}`;
  }
  const detected = prediction.detected && (!requireContrast || prediction.markerContrast) && (!wantsPattern || Boolean(tag));
  showBox('prediction', detected ? prediction.bbox : null);
  showBox('target', showTruth ? frame.bbox : null);
  let outcome = 'No detection';
  if (detected) outcome = wantsPattern ? `Dock detected · ${tag} marker · ${resolution}` : 'Dock detected';
  else if (prediction.detected) outcome = !prediction.markerContrast
    ? 'Candidate rejected · weak marker contrast' : `No printed ID read · ${resolution}`;
  element('result').textContent = outcome;
  element('score').textContent = `Score ${prediction.score.toFixed(6)} · threshold ${model.threshold.toFixed(6)}`;
  let comparison = '';
  if (showTruth) {
    if (frame.bbox && detected) comparison = `Box overlap (IoU) ${overlap(frame.bbox, prediction.bbox).toFixed(2)}`;
    else if (frame.bbox) comparison = 'Visible dock missed';
    else if (detected) comparison = 'False detection';
    else comparison = 'No visible target';
  }
  element('overlap').textContent = comparison;
}

function degrees(value) {
  return `${Number(value.toFixed(1))}°`;
}

function hasDetail() {
  return isOrbit() || frame.condition === 'survivors' || frame.condition === 'pattern-examples';
}

function readDetail() {
  const scale = replay.scale, w = model.width*scale, h = model.height*scale;
  sensor.width = w;
  sensor.height = h;
  if (isOrbit()) {
    const image = renderDockView(faces, index, frame.elevation, element('markers').checked, w, h);
    sensorContext.putImageData(new ImageData(image.rgba,w,h),0,0);
  } else {
    const sx = (frame.tile % replay.columns)*w, sy = Math.floor(frame.tile/replay.columns)*h;
    sensorContext.drawImage(detailSprite,sx,sy,w,h,0,0,w,h);
  }
  const [x,y,r,b] = detailCrop(prediction.bbox,w,h,scale);
  if (r<=x || b<=y) return null;
  const crop = sensorContext.getImageData(x,y,r-x,b-y);
  return readDockPattern(crop.data,crop.width,crop.height,[0,0,crop.width,crop.height],codes);
}

function drawFrame() {
  const {width, height} = views;
  let pixels;
  if (isOrbit()) {
    const elevation=Number(element('elevation').value);
    const rendered=renderDockView(faces,index,elevation,element('markers').checked,width,height);
    frame={azimuth:index, elevation, condition:'orbit', bbox:rendered.bbox};
    pixels=new ImageData(rendered.rgba,width,height);
    context.putImageData(pixels,0,0);
    element('elevation-value').textContent=degrees(elevation);
    element('frame-info').textContent='Browser-rendered dock';
  } else {
    frame=frames[index];
    const recorded = hasDetail();
    const columns = recorded ? replay.columns : views.columns;
    const column = frame.tile % columns;
    const row = Math.floor(frame.tile / columns);
    context.drawImage(recorded ? replaySprite : sprite, column * width, row * height, width, height, 0, 0, width, height);
    pixels=context.getImageData(0,0,width,height);
    const sample = frame.negative_kind === 'decoy' ? ' · Look-alike object' : '';
    element('frame-info').textContent = `Held-out view ${index + 1} of ${frames.length}${sample}${recorded ? ' · Seed ' + frame.seed : ''}`;
  }
  // The detector receives only camera pixels. The geometry label is used by the overlay.
  prediction = detectDock(model, pixels.data);
  prediction.markerContrast = prediction.detected &&
    hasMarkerContrast(pixels.data, width, height, prediction.bbox);
  prediction.tag = prediction.markerContrast && readDockPattern(pixels.data,width,height,prediction.bbox,codes);
  element('frame').value = index;
  const orientation = `${degrees(frame.azimuth)} azimuth · ${degrees(frame.elevation)} elevation`;
  element('angle-value').textContent = isOrbit() ? degrees(index) : orientation;
  element('frame').setAttribute('aria-valuetext', orientation);
  display.setAttribute('aria-label', `${conditionNames[frame.negative_kind || frame.condition]} at ${orientation}`);
  drawOverlay();
}

function setPlaying(playing) {
  clearInterval(timer);
  timer = playing && (isOrbit() || frames?.length > 1) ? setInterval(() => {
    if (document.hidden) return;
    index = isOrbit() ? (index+6) % 360 : (index+1) % frames.length;
    drawFrame();
  }, isOrbit() ? 200 : 1600) : null;
  element('play').textContent = timer === null ? 'Play views' : 'Pause views';
  element('play').setAttribute('aria-pressed', String(timer !== null));
}

function chooseScene(value, angle) {
  setPlaying(false);
  element('condition').value = value;
  const live=value==='orbit';
  frames = groups.get(value) || [];
  element('altitude').hidden=!live;
  element('markers-label').hidden=!live;
  document.querySelector('label[for="vision-frame"]').textContent=live ? 'Azimuth' : 'Camera view';
  if (live) index=(Math.round(angle)%360+360)%360;
  else {
    const angularDistance = frame => Math.abs(((frame.azimuth - angle + 540) % 360) - 180);
    index = frames.reduce((closest, frame, i) => angularDistance(frame) < angularDistance(frames[closest]) ? i : closest, 0);
  }
  element('frame').max = live ? 359 : frames.length-1;
  for (const id of ['frame', 'play', 'prev', 'next']) element(id).disabled = !live && frames.length === 1;
  drawFrame();
}

async function start() {
  let layout;
  [model, views, layout, replay] = await Promise.all([json('dock-detector.json'), json('dock-vision-views.json?v=2'), json('dock-vision-layout.json'),json('dock-survivors.json')]);
  faces=dockFaces(layout);
  codes=markerCodebook(layout.panels);
  if (model.width !== views.width || model.height !== views.height || !views.frames.length) {
    throw new Error('The detector and camera view dimensions do not match');
  }
  [sprite, replaySprite, detailSprite] = await Promise.all([loadSprite(views.sprite+'?v=2'), loadSprite(replay.sprite), loadSprite(replay.detail)]);
  display.width = views.width;
  display.height = views.height;
  element('boxes').setAttribute('viewBox', `0 0 ${views.width} ${views.height}`);
  groups = new Map();
  for (const frame of [...views.frames, ...replay.frames]) {
    const key = frame.negative_kind || frame.condition;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(frame);
    // Keep older shared links to the combined set of absent-dock frames usable.
    if (frame.negative_kind) {
      if (!groups.has('negative')) groups.set('negative', []);
      groups.get('negative').push(frame);
    }
  }
  for (const frames of groups.values()) frames.sort((a, b) => a.azimuth - b.azimuth || a.elevation - b.elevation);
  element('condition').add(new Option(conditionNames.orbit,'orbit'));
  const heldOut=document.createElement('optgroup');
  heldOut.label='Held-out camera views';
  element('condition').append(heldOut);
  for (const condition of Object.keys(conditionNames)) {
    if (groups.has(condition)) heldOut.append(new Option(conditionNames[condition], condition));
  }
  if (query.get('scene') === 'negative') heldOut.append(new Option('Dock absent', 'negative'));
  for (const id of controls) element(id).disabled = false;
  const scene = groups.has(query.get('scene')) ? query.get('scene') : 'orbit';
  element('verification').value = ['survivors','pattern-examples'].includes(scene) ? 'detail' : 'contrast';
  chooseScene(scene, query.has('angle') ? Number(query.get('angle')) || 0 : 35);
  element('truth').checked = query.get('truth') === '1';
  drawOverlay();
  element('load').hidden = true;
  element('image').hidden = false;
  element('model').textContent = `${views.width} × ${views.height} input · Inference runs on this device.`;
  if (query.get('loop') === '1' || (!matchMedia('(prefers-reduced-motion: reduce)').matches && !query.has('angle'))) setPlaying(true);

  element('truth').addEventListener('change', drawOverlay);
  element('verification').addEventListener('change', drawOverlay);
  element('condition').addEventListener('change', event => chooseScene(event.target.value, frame.azimuth));
  element('frame').addEventListener('input', event => {
    setPlaying(false);
    index = Number(event.target.value);
    drawFrame();
  });
  for (const id of ['elevation','markers']) element(id).addEventListener('input', () => {
    setPlaying(false);
    drawFrame();
  });
  for (const [id, delta] of [['prev', -1], ['next', 1]]) {
    element(id).addEventListener('click', () => {
      setPlaying(false);
      index = isOrbit() ? (index+delta*15+360)%360 : (index + delta + frames.length) % frames.length;
      drawFrame();
    });
  }
  element('play').addEventListener('click', () => setPlaying(timer === null));
}

start().catch(error => {
  setPlaying(false);
  for (const id of controls) element(id).disabled = true;
  element('truth').disabled = true;
  element('load').hidden = false;
  element('load').textContent = `Cannot open dock vision. ${error.message}`;
  element('result').textContent = 'Detector unavailable';
});
