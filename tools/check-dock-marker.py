"""Compare the browser detector with and without marker contrast on fresh synthetic frames."""
import argparse
import base64
from collections import Counter, defaultdict
import json
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
const scale = Number(process.argv[1]);
const layout = JSON.parse(readFileSync('assets/sim/dock-vision-layout.json'));
const codes = markerCodebook(layout.panels);
import {dockReference, locateDock} from './assets/sim/dock-localization.mjs';
const reference = dockReference(layout);
const model = JSON.parse(readFileSync('assets/sim/dock-detector.json'));
for await (const line of createInterface({input: process.stdin})) {
  if (line.startsWith('locate ')) {
    const mono = Buffer.from(line.slice(7),'base64');
    const fit = locateDock(mono,model.width*scale,model.height*scale,reference);
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
  console.log(JSON.stringify({bbox, score, detected, marked, tag, crop:detailCrop(bbox,model.width*scale,model.height*scale,scale)}));
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


def qualify(base_seed, export_loop, scale):
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
                    fit = exchange(runtime, 'locate ' + base64.b64encode(mono).decode('ascii'))
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
                    if case == 'marked':
                        counts[case]['gained'] += int(fit_hit and not baseline_hit)
                        counts[case]['lost'] += int(baseline_hit and not fit_hit)
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=712100)
    parser.add_argument('--export-loop', action='store_true')
    parser.add_argument('--sensor-scale', type=int, choices=(4,8), default=8)
    args = parser.parse_args()
    results = qualify(args.seed, args.export_loop, args.sensor_scale)
    print(f'Case       Frames   Raw   Contrast   Pattern   With {args.sensor_scale}x sensor   Invisible ID   CAD fit')
    for name, row in results.items():
        print(f"{name:10} {row['frames']:6d} {row['detected']:5d} {row['marked']:8d} {row['tag']:8d} {row['detail']:16d} {row['invisible_id']:14d} {row['fit']:9d}")
    print('Marked docks gained / lost:', results['marked']['gained'], results['marked']['lost'])
    print('Visible cases count correct localizations (IoU >= 0.5). Absent cases count false alarms.')
    if results['marked']['marked'] < .90 * results['marked']['detected']:
        raise SystemExit('Too many marked dock localizations lost')
    if results['decoy']['marked'] >= results['decoy']['detected']:
        raise SystemExit('Look-alike false alarms did not improve')
    if args.seed == 712100 and args.sensor_scale == 8:
        if results['decoy']['detail'] or results['marked']['detail'] < 40:
            raise SystemExit('Printed-ID regression on the original eight look-alikes or 40 marked docks')
