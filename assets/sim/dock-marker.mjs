// The printed tiles have dark ink bordered by light filament. Search only inside
// the detector's candidate box so unrelated detail elsewhere cannot confirm it.
export function hasMarkerContrast(rgba, width, height, box) {
  const left = Math.max(0, Math.ceil(box[0]));
  const top = Math.max(0, Math.ceil(box[1]));
  const right = Math.min(width, Math.ceil(box[2]));
  const bottom = Math.min(height, Math.ceil(box[3]));
  const axes = [[1, 0], [0, 1], [1, 1], [-1, 1]];
  let centers = 0;
  for (let y = top; y < bottom; y++) {
    for (let x = left; x < right; x++) {
      const i = 4 * (y * width + x);
      const dark = Math.max(rgba[i], rgba[i+1], rgba[i+2]);
      if (dark > 95) continue;
      // At this camera resolution a stripe is typically one to three pixels wide.
      const stripe = axes.some(([dx, dy]) => {
        for (let radius = 1; radius <= 3; radius++) {
          if (x - Math.abs(dx)*radius < left || x + Math.abs(dx)*radius >= right ||
              y - dy*radius < top || y + dy*radius >= bottom) break;
          const offset = 4 * radius * (dy * width + dx);
          const a = i-offset, b = i+offset;
          const light = Math.min(rgba[a], rgba[a+1], rgba[a+2], rgba[b], rgba[b+1], rgba[b+2]);
          if (light - dark >= 65) return true;
        }
        return false;
      });
      if (stripe && ++centers >= 2) return true;
    }
  }
  return false;
}
