"""Train and qualify a single-dock detector on camera pixels from the synthetic chair."""
import argparse
import json
import math
import os
from pathlib import Path

# Small dense layers train faster here without spawning a thread per CPU core.
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import numpy as np
from PIL import Image

from dock_vision_scene import render_scene

WIDTH, HEIGHT = 96, 72
GRID = 4
WINDOW_WIDTHS = (14, 21, 30, 42, 58, 78, 94)
ASPECTS = (.50, .75, 1.05)
KINDS = ('marked', 'occluded', 'hidden', 'empty', 'decoy', 'full')
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets/sim'


def make_windows():
    boxes = []
    for width in WINDOW_WIDTHS:
        for aspect in ASPECTS:
            height = round(width * aspect)
            if height > HEIGHT:
                continue
            # Include the final boundary explicitly so edge subjects can be found.
            step = max(3, round(width / 4))
            for top in sorted({*range(0, HEIGHT-height+1, step), HEIGHT-height}):
                for left in sorted({*range(0, WIDTH-width+1, step), WIDTH-width}):
                    boxes.append((left, top, left+width, top+height))
    return np.asarray(boxes, dtype=np.float32)


def iou(boxes, target):
    lo = np.maximum(boxes[:, :2], target[:2])
    hi = np.minimum(boxes[:, 2:], target[2:])
    area = np.prod(np.maximum(0, hi-lo), axis=1)
    return area / np.maximum(1., np.prod(boxes[:, 2:]-boxes[:, :2], axis=1)
                             + np.prod(target[2:]-target[:2]) - area)


def grid_indices(boxes):
    # Include one eighth of the window outside each edge to observe the boundary.
    t = np.linspace(-.125, 1.125, GRID+1, dtype=np.float32)
    w = boxes[:, 2] - boxes[:, 0]
    h = boxes[:, 3] - boxes[:, 1]
    xs = np.clip(np.floor(boxes[:, 0, None] + w[:, None]*t + .5), 0, WIDTH).astype(int)
    ys = np.clip(np.floor(boxes[:, 1, None] + h[:, None]*t + .5), 0, HEIGHT).astype(int)
    return xs, ys


def image_channels(rgb):
    r, g, b = np.asarray(rgb, dtype=np.float32).transpose(2, 0, 1) / 255
    gray = .299*r + .587*g + .114*b
    dx = np.zeros_like(gray)
    dy = np.zeros_like(gray)
    dx[:, 1:] = gray[:, 1:] - gray[:, :-1]
    dy[1:] = gray[1:] - gray[:-1]
    channels = np.stack([gray, r-g, b-g, np.abs(dx), np.abs(dy), gray*gray,
                         (gray < .22).astype(np.float32), (gray > .78).astype(np.float32)], axis=2)
    return np.pad(channels.cumsum(axis=0,dtype=np.float64).cumsum(axis=1), ((1,0),(1,0),(0,0)))


def features(integral, grid):
    xs, ys = grid
    corners = integral[ys[:, :, None], xs[:, None, :]]
    sums = corners[:, 1:, 1:] - corners[:, :-1, 1:] - corners[:, 1:, :-1] + corners[:, :-1, :-1]
    area = np.diff(ys)[:, :, None] * np.diff(xs)[:, None, :]
    return (sums / np.maximum(1, area)[..., None]).reshape(len(xs), -1).astype(np.float32)


def encode(boxes, target):
    spans = boxes[:, 2:] - boxes[:, :2]
    sizes = target[2:] - target[:2]
    return np.hstack([((target[:2]+target[2:])/2 - (boxes[:, :2]+boxes[:, 2:])/2)/spans,
                      np.log(sizes/spans)])


def decode(box, offsets):
    spans = box[2:]-box[:2]
    centre = (box[:2]+box[2:])/2 + np.clip(offsets[:2], -.6, .6)*spans
    half = np.exp(np.clip(offsets[2:], -.8, .8))*spans/2
    return np.clip(np.r_[centre-half, centre+half], 0, [WIDTH, HEIGHT, WIDTH, HEIGHT])


def make_frame(seed, angle, elev, kind):
    occlusion = {'occluded':'partial', 'hidden':'markers_hidden', 'full':'full'}.get(kind, 'none')
    pixels, box, meta = render_scene(seed, float(angle), elevation_deg=float(elev), size=(WIDTH, HEIGHT),
                                    present=kind not in ('empty','decoy'), hard_negative=kind == 'decoy',
                                    occlusion=occlusion)
    # A fully hidden object and an empty frame both require abstention.
    box = None if kind in ('empty','decoy','full') or box is None else np.asarray(box, dtype=np.float32)
    return np.asarray(pixels, dtype=np.uint8), box, meta


def training_set(boxes, grid):
    rng = np.random.default_rng(81437)
    all_x, all_y = [], []
    # Each angular sector has distinct bands for training, tuning and testing.
    kinds = ['marked']*6 + ['occluded']*2 + ['hidden']*2 + ['empty', 'decoy', 'decoy', 'full']
    for i in range(1008):
        kind = kinds[i % len(kinds)]
        angle = ((i // len(kinds)) % 12)*30 + rng.uniform(1, 14)
        pixels, target, _ = make_frame(10000+i, angle, rng.uniform(6, 64), kind)
        score = iou(boxes, target) if target is not None else np.zeros(len(boxes))
        ids = []
        for mask, count in [(score > .55, 16), ((score >= .12) & (score < .35), 16), (score < .12, 18)]:
            pool = np.flatnonzero(mask)
            ids.extend(rng.choice(pool, min(count, len(pool)), replace=False))
        chosen = boxes[ids]
        labels = np.zeros((len(ids), 5), dtype=np.float32)
        positive = score[ids] > .55
        labels[positive, 0] = 1
        if positive.any():
            labels[positive, 1:] = encode(chosen[positive], target)
        all_x.append(features(image_channels(pixels), (grid[0][ids], grid[1][ids])))
        all_y.append(labels)
    return np.concatenate(all_x), np.concatenate(all_y)


def sigmoid(x):
    return 1/(1+np.exp(-np.clip(x, -40, 40)))


def train(x, labels):
    rng = np.random.default_rng(8401)
    mean = x.mean(axis=0)
    variance = np.zeros_like(mean, dtype=np.float64)
    for start in range(0, len(x), 512):
        variance += np.square(x[start:start+512]-mean).sum(axis=0)
    inv = (1 / np.maximum(np.sqrt(variance/len(x)), .025)).astype(np.float32)
    shapes = [(x.shape[1], 48), (48,), (48, 24), (24,), (24, 5), (5,)]
    params = [(rng.standard_normal(shape)*math.sqrt(2/shape[0])).astype(np.float32)
              if len(shape)==2 else np.zeros(shape, dtype=np.float32) for shape in shapes]
    m = [np.zeros_like(w) for w in params]
    v = [np.zeros_like(w) for w in params]
    step = 0
    for epoch in range(34):
        lr = .0015 if epoch < 22 else .00055
        order = rng.permutation(len(x))
        for start in range(0, len(order), 192):
            ix = order[start:start+192]
            f, y = (x[ix]-mean)*inv, labels[ix]
            w1,b1,w2,b2,wo,bo = params
            h1 = np.maximum(0, f@w1+b1)
            h2 = np.maximum(0, h1@w2+b2)
            out = h2@wo+bo
            diff = out-y
            diff[:, 0] = (sigmoid(out[:, 0])-y[:, 0])*(1+2*y[:, 0])
            diff[:, 1:] = np.clip(diff[:, 1:], -.5, .5)*(8*y[:, :1])
            diff /= len(ix)
            d2 = (diff@wo.T)*(h2>0)
            d1 = (d2@w2.T)*(h1>0)
            grads = [f.T@d1, d1.sum(0), h1.T@d2, d2.sum(0), h2.T@diff, diff.sum(0)]
            step += 1
            rate = lr*math.sqrt(1-.999**step)/(1-.9**step)
            for j,grad in enumerate(grads):
                m[j] *= .9
                m[j] += .1*grad
                v[j] *= .999
                v[j] += .001*grad*grad
                params[j] -= rate*m[j]/(np.sqrt(v[j])+1e-8)
    return mean, inv, params


def infer_windows(raw, model):
    mean, inv, (w1,b1,w2,b2,wo,bo) = model
    x = (raw-mean)*inv
    h = np.maximum(0, x@w1+b1)
    h = np.maximum(0, h@w2+b2)
    return h@wo+bo


def predict(pixels, boxes, grid, model):
    out = infer_windows(features(image_channels(pixels), grid),model)
    idx = np.argmax(out[:, 0])
    return float(sigmoid(out[idx, 0])), decode(boxes[idx], out[idx, 1:])


def mine_difficult_windows(boxes, grid, model, base_seed):
    # Replay high-scoring mistakes from fresh training-band scenes. Without
    # this stage, the maximum across thousands of windows often fires on clutter.
    rng = np.random.default_rng(base_seed)
    all_x, all_y = [], []
    for i in range(420):
        kind = KINDS[i%len(KINDS)]
        rgb, target, _ = make_frame(base_seed+i, ((i//len(KINDS))%12)*30+rng.uniform(1,14), rng.uniform(6,64), kind)
        overlap = np.zeros(len(boxes)) if target is None else iou(boxes,target)
        raw = features(image_channels(rgb),grid)
        score = infer_windows(raw,model)[:,0]
        available = overlap < .35
        # Mine distinct errors rather than many copies of the same patch.
        difficult = []
        for idx in np.argsort(-score):
            if not available[idx]:
                continue
            difficult.append(idx)
            if len(difficult) == 12:
                break
            available &= iou(boxes,boxes[idx]) < .60
        positives = np.flatnonzero(overlap > .55)
        if len(positives):
            positives = positives[np.argsort(score[positives])[:12]]
        chosen = np.r_[np.asarray(difficult,dtype=int), positives]
        labels = np.zeros((len(chosen),5),dtype=np.float32)
        if len(positives):
            labels[len(difficult):,0] = 1
            labels[len(difficult):,1:] = encode(boxes[positives],target)
        all_x.append(raw[chosen])
        all_y.append(labels)
    return np.concatenate(all_x),np.concatenate(all_y)


def evaluate(boxes, grid, model, *, test=False):
    rng = np.random.default_rng(84217 if test else 671)
    rows = []
    repeats = 4 if test else 2
    for rep in range(repeats):
        for sector in range(12):
            for j, kind in enumerate(KINDS):
                angle = sector*30 + rng.uniform(23, 28) if test else sector*30 + rng.uniform(17, 20)
                elevation = rng.uniform(6+rep*14, 19+rep*14) if test else rng.uniform(6, 64)
                seed = (145000 if test else 50000)+len(rows)
                rgb, target, meta = make_frame(seed, angle, elevation, kind)
                score,predicted = predict(rgb, boxes, grid, model)
                row = dict(seed=seed,azimuth=float(angle),elevation=float(elevation),condition=kind,
                           score=score,predicted_bbox=predicted.tolist(),bbox=target.tolist() if target is not None else None,
                           iou=float(iou(predicted[None,:],target)[0]) if target is not None else None)
                if 'visible_marker_count' in meta:
                    row['visible_markers'] = int(meta['visible_marker_count'])
                rows.append(row)
    return rows


def measures(rows, threshold):
    positive = [r for r in rows if r['bbox'] is not None]
    absent = [r for r in rows if r['bbox'] is None]
    count = sum(r['score'] >= threshold and r['iou'] >= .50 for r in positive)
    hits = sum(r['score'] >= threshold for r in positive)
    false = sum(r['score'] >= threshold for r in absent)
    precision = count/max(1,hits+false)
    recall = count/max(1,len(positive))
    return dict(positive=len(positive),negative=len(absent),localized=count,positive_detections=hits,
                false_positives=false,precision=precision,recall=recall,
                f1=2*precision*recall/max(1e-10,precision+recall))


def marker_ablation(rows, threshold, model, boxes, grid):
    counts = dict(pairs=0, both_localized=0, marked_only=0, hidden_only=0, neither=0)
    for row in rows:
        if row['condition'] != 'marked':
            continue
        localized = []
        for kind in ('marked', 'hidden'):
            rgb, target, _ = make_frame(row['seed'], row['azimuth'], row['elevation'], kind)
            score, predicted = predict(rgb,boxes,grid,model)
            localized.append(score >= threshold and iou(predicted[None,:],target)[0] >= .50)
        key = ('neither','hidden_only','marked_only','both_localized')[2*int(localized[0])+int(localized[1])]
        counts[key] += 1
        counts['pairs'] += 1
    return counts


def write_json(path, data):
    path.write_text(json.dumps(data, separators=(',',':'), allow_nan=False)+'\n',encoding='utf8')


def export_gallery(result):
    selected = []
    additional_decoys = []
    for index, row in enumerate(result['trials']):
        repeat, within = divmod(index, 12*len(KINDS))
        sector = within // len(KINDS)
        kind = row['condition']
        if (kind == 'marked' and repeat == sector % 4) or (kind != 'marked' and repeat == 0 and sector % 3 == 0):
            selected.append(row)
        elif kind == 'decoy':
            additional_decoys.append(row)
    selected.sort(key=lambda row: (KINDS.index(row['condition']), row['azimuth']))
    selected.extend(additional_decoys)
    columns = 8
    sheet = Image.new('RGB',(columns*WIDTH,math.ceil(len(selected)/columns)*HEIGHT))
    frames=[]
    for index, row in enumerate(selected):
        rgb, _, _ = make_frame(row['seed'], row['azimuth'], row['elevation'], row['condition'])
        sheet.paste(Image.fromarray(rgb),(index%columns*WIDTH,index//columns*HEIGHT))
        frames.append(dict(tile=index,**{**row,'condition':'negative' if row['condition'] in ('empty','decoy') else row['condition']},
                           negative_kind=row['condition'] if row['condition'] in ('empty','decoy') else None,
                           detected=row['score']>=result['threshold']))
    sheet.save(ASSETS/'dock-vision-views.png')
    write_json(ASSETS/'dock-vision-views.json',dict(width=WIDTH,height=HEIGHT,columns=columns,
        sprite='dock-vision-views.png',frames=frames,summary={k:result[k] for k in ('train_scenes','validation_scenes','test_scenes','validation','test','by_condition')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    args = parser.parse_args()
    boxes = make_windows()
    grid = grid_indices(boxes)
    x, y = training_set(boxes,grid)
    print('training patches:',x.shape,'positive:',int(y[:,0].sum()),flush=True)
    model = train(x,y)
    for base_seed in (30000, 36000):
        hard_x, hard_y = mine_difficult_windows(boxes,grid,model,base_seed)
        x = np.concatenate((x,hard_x))
        y = np.concatenate((y,hard_y))
        del hard_x, hard_y
        print('retraining with mined patches:', len(x),flush=True)
        model = train(x,y)
    del x,y
    val = evaluate(boxes,grid,model)
    # Select the operating point only on the independent tuning set.
    candidates = sorted({r['score'] for r in val}|{1.})
    threshold = max(candidates,key=lambda t: (measures(val,t)['f1'],t))
    lower = max((v for v in candidates if v < threshold), default=threshold)
    threshold = (lower+threshold)/2
    rows = evaluate(boxes,grid,model,test=True)
    result = dict(train_scenes=1848,validation_scenes=len(val),test_scenes=len(rows),threshold=threshold,
                  validation=measures(val,threshold),test=measures(rows,threshold),
                  by_condition={k:measures([r for r in rows if r['condition']==k],threshold) for k in KINDS},
                  by_sector={str(s):measures([r for r in rows if int(r['azimuth']//30)==s],threshold) for s in range(12)},
                  trials=rows)
    result['paired_marker_ablation'] = marker_ablation(rows,threshold,model,boxes,grid)
    mean,inv,p = model
    export = dict(format='dock-window-mlp-v1',width=WIDTH,height=HEIGHT,threshold=threshold,
                  boxes=boxes.astype(int).tolist(),mean=mean.tolist(),inv_std=inv.tolist(),
                  layers=[dict(inputs=w.shape[0],outputs=w.shape[1],weight=w.ravel().tolist(),bias=b.tolist())
                          for w,b in zip(p[::2],p[1::2])])
    write_json(ASSETS/'dock-detector.json',export)
    write_json(args.results,result)
    export_gallery(result)
    print(json.dumps({k:result[k] for k in ('threshold','validation','test','by_condition')},indent=2))


if __name__=='__main__':
    main()
