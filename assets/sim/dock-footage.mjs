import {detectDock} from './dock-inference.mjs';
import {hasMarkerContrast} from './dock-marker.mjs';
import {detailCrop, markerLuminance, readDockPattern} from './dock-pattern.mjs?v=2';
import {locateDock} from './dock-localization.mjs';

export function intersectionOverUnion(a, b) {
  const area = ([l,t,r,bottom]) => Math.max(0,r-l)*Math.max(0,bottom-t);
  const intersection = area([Math.max(a[0],b[0]),Math.max(a[1],b[1]),
    Math.min(a[2],b[2]),Math.min(a[3],b[3])]);
  return intersection / (area(a) + area(b) - intersection || 1);
}

export function frameOutcome(frame, detection) {
  if (frame.truth === 'unknown') return 'unlabelled';
  if (frame.truth === 'absent') return detection ? 'false alarm' : 'clear';
  if (!detection) return 'miss';
  return frame.box && intersectionOverUnion(frame.box,detection.bbox) < .5 ? 'wrong box' : 'hit';
}

export function differs(a, b) {
  return Boolean(a) !== Boolean(b) || Boolean(a && b && intersectionOverUnion(a.bbox,b.bbox) < .5);
}

export function fallbackDock(mlp, cad) {
  if (mlp) return {...mlp, source:'mlp'};
  return cad ? {...cad, source:'cad'} : null;
}

export function compareDockFrame(model, reference, native, detail, fitted) {
  const w = detail.width, h = detail.height;
  const normalize = box => box.map((value,i) => value/(i%2 ? h : w));
  const began = performance.now();
  const raw = detectDock(model,native.data);
  const contrast = raw.detected && hasMarkerContrast(native.data,model.width,model.height,raw.bbox);
  const bbox = raw.bbox.map((value,i) => {
    const axis = i%2;
    return Math.max(0, Math.min(axis ? h : w, (value-fitted.offset[axis])/fitted.scale));
  });
  let tag = contrast ? readDockPattern(native.data,model.width,model.height,raw.bbox,reference.codes) : null;
  if (contrast && !tag) {
    const crop = detailCrop(bbox,w,h,1);
    tag = readDockPattern(detail.data,w,h,crop,reference.codes);
  }
  const validBox = bbox[0]<bbox[2] && bbox[1]<bbox[3];
  const mlp = tag && validBox ? {bbox:normalize(bbox),ids:[tag]} : null;
  const mlpMs = performance.now() - began;
  const fit = locateDock(markerLuminance(detail.data),w,h,reference);
  const cad = fit && fit.bbox[0]<fit.bbox[2] && fit.bbox[1]<fit.bbox[3]
    ? {...fit,bbox:normalize(fit.bbox)} : null;
  return {
    mlp, cad, fallback:fallbackDock(mlp,cad), mlpMs, cadMs:performance.now()-began-mlpMs,
    mlpScore:raw.score, mlpThreshold:model.threshold, mlpProposal:validBox ? normalize(bbox) : null,
    mlpStage:!raw.detected ? 'below threshold' : !contrast ? 'weak contrast' : !mlp ? 'no printed ID' : 'accepted',
  };
}
