// Match tools/train-dock-vision.py. Only camera pixels enter feature extraction.
const compiledModels = new WeakMap();
const CHANNELS = 8;
const GRID = 4;

function prepare(model) {
  if (model.format !== 'dock-window-mlp-v1' || model.width !== 96 || model.height !== 72) {
    throw new Error('Unsupported dock detector format.');
  }
  const {width, height} = model;
  const windows = model.boxes.map(box => {
    const axis = (start, end, limit) => Array.from({length:GRID+1}, (_, i) =>
      Math.max(0, Math.min(limit, Math.floor(start + (end-start)*(-.125 + i*1.25/GRID) + .5))));
    return {box, xs:axis(box[0], box[2], width), ys:axis(box[1], box[3], height)};
  });
  const layers = model.layers.map(layer => ({
    ...layer, weight:new Float32Array(layer.weight), bias:new Float32Array(layer.bias),
  }));
  return {windows, layers};
}

function channelIntegrals(rgba, width, height) {
  const stride = (width+1)*CHANNELS;
  const integral = new Float64Array((height+1)*stride);
  const previousRow = new Float32Array(width);
  const sums = new Float64Array(CHANNELS);
  for (let y = 0; y < height; y++) {
    let left = 0;
    sums.fill(0);
    for (let x = 0; x < width; x++) {
      const pixel = (y*width+x)*4;
      const r = Math.fround(rgba[pixel]/255), g = Math.fround(rgba[pixel+1]/255), b = Math.fround(rgba[pixel+2]/255);
      const gray = Math.fround(Math.fround(Math.fround(Math.fround(.299)*r) + Math.fround(Math.fround(.587)*g))
        + Math.fround(Math.fround(.114)*b));
      sums[0] += gray;
      sums[1] += r-g;
      sums[2] += b-g;
      if (x > 0) sums[3] += Math.abs(gray-left);
      if (y > 0) sums[4] += Math.abs(gray-previousRow[x]);
      // Each pixel's channel includes its own local gradient, accumulated across the row.
      sums[5] += gray*gray;
      sums[6] += gray < Math.fround(.22);
      sums[7] += gray > Math.fround(.78);
      left = previousRow[x] = gray;
      const index = (y+1)*stride + (x+1)*CHANNELS;
      for (let c = 0; c < CHANNELS; c++) integral[index+c] = sums[c]+integral[index-stride+c];
    }
  }
  return integral;
}

function describe(integral, width, window, model, output) {
  const {xs, ys} = window;
  let k = 0;
  for (let y=0; y<GRID; y++) for (let x=0; x<GRID; x++) {
    const x0 = xs[x], x1 = xs[x+1], y0 = ys[y], y1 = ys[y+1];
    const area = Math.max(1,(x1-x0)*(y1-y0));
    const a = ((width+1)*y0+x0)*CHANNELS, b = ((width+1)*y0+x1)*CHANNELS;
    const c = ((width+1)*y1+x0)*CHANNELS, d = ((width+1)*y1+x1)*CHANNELS;
    for (let ch = 0; ch < CHANNELS; ch++, k++) {
      const mean = (integral[d+ch] - integral[b+ch] - integral[c+ch] + integral[a+ch])/area;
      output[k] = (mean-model.mean[k])*model.inv_std[k];
    }
  }
}

function dense(layer, input, output, relu) {
  const {outputs:n, weight, bias} = layer;
  output.set(bias);
  let k = 0;
  for (let i = 0; i < input.length; i++) {
    const v = input[i];
    for (let j = 0; j < n; j++, k++) output[j] += v*weight[k];
  }
  if (relu) for (let j = 0; j < n; j++) output[j] = Math.max(0,output[j]);
}

export function detectDock(model, rgba) {
  const {width, height} = model;
  if (rgba.length !== width*height*4) throw new Error('Unexpected dock camera frame dimensions.');
  if (!compiledModels.has(model)) compiledModels.set(model, prepare(model));
  const {windows, layers} = compiledModels.get(model);
  const integral = channelIntegrals(rgba, width, height);
  const input = new Float32Array(model.mean.length);
  const layersOut = layers.map(layer => new Float64Array(layer.outputs));
  let logit = -Infinity, bestWindow = null, offsets = null;
  for (const window of windows) {
    describe(integral, width, window, model, input);
    let values = input;
    for (let i = 0; i < layers.length; i++) {
      dense(layers[i], values, layersOut[i], i < layers.length-1);
      values = layersOut[i];
    }
    if (values[0] > logit) {
      logit = values[0];
      bestWindow = window.box;
      offsets = values.slice(1);
    }
  }
  const score = Math.fround(1/(1+Math.exp(-Math.min(40, Math.max(-40, logit)))));
  const [x0, y0, x1, y1] = bestWindow;
  const w = x1-x0, h = y1-y0;
  const clip = (v, limit) => Math.min(limit, Math.max(-limit, v));
  const cx = (x0+x1)/2 + clip(offsets[0], .6)*w, cy = (y0+y1)/2 + clip(offsets[1], .6)*h;
  const rx = Math.exp(clip(offsets[2], .8))*w/2, ry = Math.exp(clip(offsets[3], .8))*h/2;
  const bound = (n, limit) => Math.max(0,Math.min(limit,n));
  return {bbox:[bound(cx-rx,width),bound(cy-ry,height),bound(cx+rx,width),bound(cy+ry,height)],
    score, detected:score >= model.threshold};
}
