"""Compare the browser detector with and without marker contrast on fresh synthetic frames."""
import argparse
import base64
from collections import Counter, defaultdict
import json
from io import BytesIO
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image

from dock_vision_scene import PANELS, render_scene


ROOT = Path(__file__).resolve().parents[1]
RUNNER = """
import {createInterface} from 'node:readline';
import {readFileSync} from 'node:fs';
import {detectDock} from './assets/sim/dock-inference.mjs';
import {hasMarkerContrast} from './assets/sim/dock-marker.mjs';
import {markerCodebook, readDockPattern, detailCrop} from './assets/sim/dock-pattern.mjs';
import {fallbackDock, preferCadDock} from './assets/sim/dock-footage.mjs';
const scale = Number(process.argv[1]);
const layout = JSON.parse(readFileSync('assets/sim/dock-vision-layout.json'));
const codes = markerCodebook(layout.panels);
import {dockReference, inspectDock, recoverOccludedDock} from './assets/sim/dock-localization.mjs';
const reference = dockReference(layout);
const model = JSON.parse(readFileSync('assets/sim/dock-detector.json'));
for await (const line of createInterface({input: process.stdin})) {
  if (line.startsWith('fallback ')) {
    const {mlp,cad} = JSON.parse(line.slice(9));
    console.log(JSON.stringify({mlp,cad,mlpFirst:fallbackDock(mlp,cad),cadFirst:preferCadDock(mlp,cad)}));
    continue;
  }
  if (line.startsWith('locate ')) {
    const inspected = inspectDock(Buffer.from(line.slice(7),'base64'),model.width*scale,model.height*scale,reference);
    if (inspected.standard) inspected.standard.bbox = inspected.standard.bbox.map(v=>v/scale);
    console.log(JSON.stringify(inspected));
    continue;
  }
  if (line.startsWith('recover ')) {
    const fit = recoverOccludedDock(Buffer.from(line.slice(8),'base64'),model.width*scale,model.height*scale,reference);
    if (fit) fit.bbox = fit.bbox.map(v=>v/scale);
    console.log(JSON.stringify(fit));
    continue;
  }
  if (line.startsWith('detail ')) {
    const [,width,height,data] = line.split(' ');
    const pixels = Buffer.from(data, 'base64');
    const tag = readDockPattern(pixels,+width,+height,[0,0,+width,+height],codes);
    console.log(JSON.stringify({tag}));
    continue;
  }
  const pixels = Buffer.from(line, 'base64');
  const {bbox, score, detected} = detectDock(model, pixels);
  const marked = detected && hasMarkerContrast(pixels, model.width, model.height, bbox);
  const tag = marked && readDockPattern(pixels, model.width, model.height, bbox, codes);
  console.log(JSON.stringify({bbox, score, threshold:model.threshold, detected, marked, tag,
    crop:detailCrop(bbox,model.width*scale,model.height*scale,scale)}));
}
"""


def overlap(first, second):
    def area(box):
        return max(0, box[2]-box[0]) * max(0, box[3]-box[1])
    intersection = area([max(first[0], second[0]), max(first[1], second[1]),
                         min(first[2], second[2]), min(first[3], second[3])])
    return intersection / max(1, area(first) + area(second) - intersection)


def pixels64(rgb):
    rgba = np.empty((*rgb.shape[:2], 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = 255
    return base64.b64encode(rgba).decode('ascii')


def exchange(runtime, line):
    runtime.stdin.write(line + '\n')
    runtime.stdin.flush()
    return json.loads(runtime.stdout.readline())


def replay_frame(seed, sweep, view, bbox, decisions, mlp_result, replay, *, diagnosis=None):
    def normalized(box):
        return [v / (72 if i % 2 else 96) for i, v in enumerate(box)]

    results = {method: dict(detection, bbox=normalized(detection['bbox'])) if detection else None
               for method, detection in decisions.items()}
    mlp_stage = ('accepted' if decisions['mlp'] else 'below threshold' if not mlp_result['detected']
                 else 'weak contrast' if not mlp_result['marked'] else 'no printed ID')
    results.update(mlpScore=mlp_result['score'], mlpThreshold=mlp_result['threshold'], mlpStage=mlp_stage)
    if diagnosis:
        results['diagnosis'] = diagnosis
    image = BytesIO()
    Image.fromarray(view).save(image, format='JPEG', quality=89)
    replay.append((dict(t=len(replay)*2600, truth='present', box=normalized(bbox), seed=seed,
                        sweep=sweep, jpeg=base64.b64encode(image.getvalue()).decode('ascii')), results))


def qualify(base_seed, export_loop, scale, order_replay=None, occlusion_replay=None):
    rng = np.random.default_rng(base_seed - 7)
    survivors, examples, misses = [], [], []
    counts = defaultdict(Counter)
    cases = {'marked': 'none', 'occluded': 'partial', 'hidden': 'markers_hidden',
             'empty': 'none', 'decoy': 'none', 'covered': 'full'}
    with subprocess.Popen(['node', '--input-type=module', '-e', RUNNER, str(scale)], cwd=ROOT,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as runtime:
        for repeat in range(4):
            for sector in range(12):
                for index, (case, obstruction) in enumerate(cases.items()):
                    seed = base_seed + (repeat*12 + sector)*len(cases) + index
                    azimuth, elevation = sector*30 + rng.uniform(0, 30), rng.uniform(6, 64)
                    scene = dict(elevation_deg=elevation, present=case not in ('empty', 'decoy'),
                                 hard_negative=case == 'decoy', occlusion=obstruction)
                    rgb, target, native_meta = render_scene(seed, azimuth, **scene)
                    result = exchange(runtime, pixels64(rgb))
                    matches = target is None or overlap(result['bbox'], target) >= .5
                    example = export_loop and case == 'marked' and matches and result['marked'] and len(examples) == repeat
                    survivor = export_loop and case == 'decoy' and result['marked']
                    tag = result['tag']
                    tag_meta = native_meta
                    detail, _, meta = render_scene(seed, azimuth, **scene, sensor_scale=scale)
                    c = detail.astype(np.uint16)
                    mono = ((c[:,:,0]+2*c[:,:,1]+c[:,:,2])//4).astype(np.uint8)
                    encoded = base64.b64encode(mono).decode('ascii')
                    inspected = exchange(runtime, 'locate ' + encoded)
                    fit = inspected['standard']
                    fit_hit = fit is not None and (target is None or overlap(fit['bbox'],target) >= .5)
                    counts[case]['fit'] += int(fit_hit)
                    if result['marked'] and (not tag or example or survivor):
                        if not tag:
                            left, top, right, bottom = result['crop']
                            crop = detail[top:bottom,left:right]
                            h, w = crop.shape[:2]
                            if w and h:
                                tag = exchange(runtime, f'detail {w} {h} {pixels64(crop)}')['tag']
                                tag_meta = meta
                        if example or survivor:
                            record = dict(seed=seed, azimuth=azimuth, elevation=elevation, bbox=target,
                                          condition='pattern-examples' if example else 'survivors')
                            # The decoder uses integer luminance. Store that channel losslessly for playback.
                            (examples if example else survivors).append((rgb, mono, record))
                    baseline_hit = bool(tag) and matches
                    decisions = exchange(runtime, 'fallback ' + json.dumps({
                        'mlp': {'bbox': result['bbox'], 'ids': [tag]} if tag else None,
                        'cad': fit,
                    }))
                    fallback = decisions['mlpFirst']
                    fallback_hit = fallback is not None and (target is None or overlap(fallback['bbox'],target) >= .5)
                    counts[case]['fallback'] += int(fallback_hit)
                    cad_first = decisions['cadFirst']
                    cad_first_hit = cad_first is not None and (target is None or overlap(cad_first['bbox'],target) >= .5)
                    counts[case]['cad_first'] += int(cad_first_hit)
                    counts[case]['mlp_backup'] += int(cad_first_hit and cad_first['source'] == 'mlp')
                    recovered = cad_first
                    if not cad_first:
                        recovered = exchange(runtime, 'recover ' + encoded)
                    recovered_hit = recovered is not None and (target is None or overlap(recovered['bbox'],target) >= .5)
                    counts[case]['recovery'] += int(recovered_hit)
                    if case == 'occluded' and not cad_first_hit:
                        diagnosis = inspected['reason'] or ('wrong CAD box' if fit else 'wrong MLP box')
                        counts[case][diagnosis] += 1
                        if occlusion_replay is not None:
                            marker_absent = not any(meta['marker_pixels'])
                            if marker_absent:
                                counts[case]['no visible marker pixels'] += 1
                            print(f"Occlusion {seed}: {diagnosis}, visible panels={meta['visible_marker_count']}, "
                                  f"marker pixels={meta['marker_pixels']}, recovery={recovered_hit}", flush=True)
                            replay_frame(seed, base_seed, mono, target, {
                                'mlp': decisions['mlp'], 'cad': fit, 'fallback': fallback,
                                'cadFirst': cad_first, 'recovered': recovered,
                            }, result, occlusion_replay, diagnosis='all markers obscured' if marker_absent else diagnosis)
                    if order_replay is not None and case == 'marked' and tag and not matches:
                        replay_frame(seed, base_seed, mono, target, {
                            'mlp': decisions['mlp'], 'cad': fit, 'fallback': fallback, 'cadFirst': cad_first,
                        }, result, order_replay)
                    if case == 'marked':
                        counts[case]['gained'] += int(fit_hit and not baseline_hit)
                        counts[case]['lost'] += int(baseline_hit and not fit_hit)
                        if not baseline_hit:
                            reason = ('below score threshold' if not result['detected']
                                      else 'weak marker contrast' if not result['marked']
                                      else 'no printed ID' if not tag else 'wrong box')
                            counts[case][reason] += 1
                            print(f"Native miss {seed}: {reason}; score={result['score']:.5f}; "
                                  f"fallback={fallback['source'] if fallback else 'none'}", flush=True)
                        if export_loop and not baseline_hit:
                            record = dict(seed=seed, azimuth=azimuth, elevation=elevation, bbox=target,
                                          condition='marked-misses')
                            misses.append((rgb,mono,record))
                            before = overlap(result['bbox'],target)
                            after = overlap(fit['bbox'],target) if fit else 0
                            print(f"Miss {seed}: score={result['score']:.5f} old IoU={before:.3f} "
                                  f"old ID={tag} fit IoU={after:.3f}",flush=True)
                    result['detail'] = tag
                    if tag:
                        panel_index = next(i for i,p in enumerate(PANELS) if p['name'] == tag)
                        counts[case]['invisible_id'] += int(tag_meta['marker_pixels'][panel_index] == 0)
                    counts[case]['frames'] += 1
                    for mode in ('detected', 'marked', 'tag', 'detail'):
                        counts[case][mode] += int(bool(result[mode]) and matches)
        runtime.stdin.close()
        if runtime.wait() != 0:
            raise RuntimeError('Browser inference process failed')
    if export_loop:
        seeds = [f['seed'] for _,_,f in survivors]
        if seeds != [712116,712188,712224,712266,712332,712344,712374,712380]:
            raise ValueError('Expected the eight original contrast false positives')
        if [f['seed'] for _,_,f in misses] != [712118,712172,712196,712202,712214,712232,712262,712280]:
            raise ValueError('Unexpected membership of the eight original missed docks')
        records = survivors + examples + misses
        columns = 4
        rows = (len(records)+columns-1)//columns
        sheet = Image.new('RGB', (96*columns, 72*rows))
        sensor = Image.new('L', (96*scale*columns, 72*scale*rows))
        for i, (rgb, mono, frame) in enumerate(records):
            frame['tile'] = i
            col, row = i%columns, i//columns
            sheet.paste(Image.fromarray(rgb), (96*col, 72*row))
            sensor.paste(Image.fromarray(mono), (96*scale*col, 72*scale*row))
        out = ROOT/'assets/sim'
        sheet.save(out/'dock-survivors.png')
        sensor.save(out/'dock-survivors-detail.png')
        (out/'dock-survivors.json').write_text(json.dumps(
            dict(width=96,height=72,columns=columns,sprite='dock-survivors.png',
                 detail='dock-survivors-detail.png',scale=scale,frames=[f for _,_,f in records]),
            indent=2)+'\n', encoding='utf8')
    return counts


def summarize(seed, scale, results):
    print(f'Sweep {seed}, {scale}x sensor detail')
    print('Case       Frames   Raw   Contrast   Pattern   With detail  Invisible ID   CAD fit  MLP first  CAD first  MLP backup  Recovery')
    for name, row in results.items():
        print(f"{name:10} {row['frames']:6d} {row['detected']:5d} {row['marked']:8d} {row['tag']:8d} "
              f"{row['detail']:13d} {row['invisible_id']:13d} {row['fit']:9d} {row['fallback']:10d} "
              f"{row['cad_first']:10d} {row['mlp_backup']:11d} {row['recovery']:9d}")
    print('Occlusion misses by CAD stage:', {reason:results['occluded'][reason]
          for reason in ('no decoded marker','pose rejected','wrong CAD box','wrong MLP box')})
    print('Marked docks gained / lost:', results['marked']['gained'], results['marked']['lost'])
    print('Visible cases count correct localizations (IoU >= 0.5). Absent cases count false alarms.')
    if results['marked']['marked'] < .90 * results['marked']['detected']:
        raise SystemExit('Too many marked dock localizations lost')
    if results['decoy']['marked'] >= results['decoy']['detected']:
        raise SystemExit('Look-alike false alarms did not improve')
    if seed == 712100 and scale == 8:
        if results['decoy']['detail'] or results['marked']['detail'] < 40:
            raise SystemExit('Printed-ID regression on the original eight look-alikes or 40 marked docks')
        if results['marked']['fallback'] < 42 or any(results[name]['fallback'] for name in ('decoy', 'empty', 'covered')):
            raise SystemExit('Fallback regression on marked docks or absent targets')
    if seed in (712100, 762400) and scale == 8:
        if results['marked']['cad_first'] != 48 or any(results[name]['cad_first'] for name in ('decoy', 'empty', 'covered')):
            raise SystemExit('CAD-first regression on a fully marked dock or absent target')
    if seed in (712100, 762400, 913100) and scale == 8:
        if results['occluded']['recovery'] < {712100:39,762400:37,913100:42}[seed]:
            raise SystemExit('The occlusion recovery missed a previously recovered case')
        if results['marked']['recovery'] != 48 or any(results[name]['recovery'] for name in ('decoy', 'empty', 'covered', 'hidden')):
            raise SystemExit('Recovery regression on a fully marked dock or on a scene without usable markers')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=712100)
    parser.add_argument('--also-seed', type=int, action='append', default=[])
    parser.add_argument('--export-loop', action='store_true')
    parser.add_argument('--export-order-loop', type=Path)
    parser.add_argument('--export-occlusion-loop', type=Path)
    parser.add_argument('--sensor-scale', type=int, choices=(4,8), default=8)
    args = parser.parse_args()
    order_replay = [] if args.export_order_loop else None
    occlusion_replay = [] if args.export_occlusion_loop else None
    sweeps = {}
    for seed in [args.seed,*args.also_seed]:
        results = qualify(seed, args.export_loop and seed == args.seed, args.sensor_scale, order_replay, occlusion_replay)
        summarize(seed, args.sensor_scale, results)
        sweeps[seed] = results
    for path, replay in [(args.export_order_loop,order_replay),(args.export_occlusion_loop,occlusion_replay)]:
        if path:
            path.write_text(json.dumps({
                'format': 'duck-lab-camera-v1', 'source': 'Synthetic sweep replay',
                'frames': [frame for frame, _ in replay],
                'decisions': [decision for _, decision in replay],
                'sweeps': sweeps,
            },separators=(',',':'))+'\n', encoding='utf8')
