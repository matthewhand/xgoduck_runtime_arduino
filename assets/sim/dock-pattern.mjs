// Read the printed layout from a camera crop. Coordinates below use pixel edges.
const cross = (a, b, c) => (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]);

// An approximate dock box can clip the side and top tiles. Keep a small rim
// of camera context around the predicted subject in the detail read.
export function detailCrop(box, width, height, scale) {
  const [l,t,r,b] = box;
  const dx=(r-l)*.20, dy=(b-t)*.20;
  return [Math.max(0,Math.floor((l-dx)*scale)),Math.max(0,Math.floor((t-dy)*scale)),
    Math.min(width,Math.ceil((r+dx)*scale)),Math.min(height,Math.ceil((b+dy)*scale))];
}

function ringCorners(points) {
  points.sort((a,b) => a[0]-b[0] || a[1]-b[1]);
  function chain(points) {
    const hull = [];
    for (const p of points) {
      while (hull.length >= 2 && cross(hull.at(-2), hull.at(-1), p) <= 0) hull.pop();
      hull.push(p);
    }
    hull.pop();
    return hull;
  }
  const hull = chain(points).concat(chain(points.reverse()));
  // Remove small pixel stair-steps from the convex boundary of the ink ring.
  while (hull.length > 4) {
    let smallest = Infinity, remove = 0;
    for (let i=0; i<hull.length; i++) {
      const area = cross(hull.at(i-1), hull[i], hull[(i+1)%hull.length]);
      if (area < smallest) { smallest = area; remove = i; }
    }
    hull.splice(remove, 1);
  }
  return hull;
}

export function markerCodebook(panels) {
  const codes = new Map();
  for (const {name, bitmap} of panels) {
    let payload = bitmap.slice(2,5).map(row => [...row.slice(2,5)]);
    for (let rotation=0; rotation<4; rotation++) {
      const key = payload.flat().join('');
      if (codes.has(key)) throw Error('Ambiguous printed marker ID or orientation');
      codes.set(key,{name, rotation});
      payload = payload[0].map((_,col) => payload.map(row => row[col]).reverse());
    }
  }
  return codes;
}

function sampleCode(quad, gray, width, height, codes, quietBorderOutliers) {
  const [a,b,c,d] = quad;
  // Homography from the unit square to the outer edge of the 5 × 5 ink region.
  const bx=b[0]-c[0], by=b[1]-c[1], dx=d[0]-c[0], dy=d[1]-c[1];
  const sx=a[0]-b[0]+c[0]-d[0], sy=a[1]-b[1]+c[1]-d[1];
  const det=bx*dy-dx*by;
  if (Math.abs(det)<1) return null;
  const g=(sx*dy-dx*sy)/det, h=(bx*sy-sx*by)/det;
  const samples=[], used = new Set(), perimeter=[], ring=[];
  for (let y=0; y<7; y++) for (let x=0; x<7; x++) {
    const u=(x-.5)/5, v=(y-.5)/5, z=1+g*u+h*v;
    const px=Math.floor((a[0]+((1+g)*b[0]-a[0])*u+((1+h)*d[0]-a[0])*v)/z);
    const py=Math.floor((a[1]+((1+g)*b[1]-a[1])*u+((1+h)*d[1]-a[1])*v)/z);
    const idx=py*width+px;
    if (!(px>=0 && px<width && py>=0 && py<height) || used.has(idx)) return null;
    used.add(idx);
    const sample=gray[idx];
    samples.push(sample);
    if (x===0 || y===0 || x===6 || y===6) perimeter.push(sample);
    else if (x===1 || y===1 || x===5 || y===5) ring.push(sample);
  }
  perimeter.sort((a,b)=>a-b);
  ring.sort((a,b)=>a-b);
  // Keep all nine payload bits and at least 15/16 ring samples. A separate
  // recovery pass can tolerate a few extra covered white-border cells.
  if (perimeter[quietBorderOutliers]-ring[14]<45) return null;
  const cut=(perimeter[12]+ring[8])/2;
  let bits='';
  for (let y=2; y<=4; y++) for (let x=2; x<=4; x++) {
    const value=samples[y*7+x];
    if (Math.abs(value-cut)<10) return null;
    bits += value<cut ? '1':'0';
  }
  return codes.get(bits) ?? null;
}

function scanPatterns(gray, width, height, box, codes, firstOnly, thresholds, quietBorderOutliers) {
  const left=Math.max(0,Math.floor(box[0])), right=Math.min(width,Math.ceil(box[2]));
  const top=Math.max(0,Math.floor(box[1])), bottom=Math.min(height,Math.ceil(box[3]));
  const found = new Map();
  for (const threshold of thresholds) {
    const visited=new Uint8Array(gray.length);
    for (let y=top; y<bottom; y++) for (let x=left; x<right; x++) {
      const start=y*width+x;
      if (visited[start] || gray[start]>threshold) continue;
      const queue=[start], points=[];
      visited[start]=1;
      // Only exposed pixel corners can contribute to the convex hull.
      for (let k=0; k<queue.length; k++) {
        const p=queue[k], col=p%width, row=Math.floor(p/width);
        const extend=(q,inside) => {
          if (!inside || gray[q]>threshold) return true;
          if (!visited[q]) { visited[q]=1; queue.push(q); }
          return false;
        };
        const west=extend(p-1,col>left), east=extend(p+1,col+1<right);
        const north=extend(p-width,row>top), south=extend(p+width,row+1<bottom);
        if (west && north) points.push([col,row]);
        if (east && north) points.push([col+1,row]);
        if (east && south) points.push([col+1,row+1]);
        if (west && south) points.push([col,row+1]);
      }
      if (queue.length<16 || points.length<4) continue;
      const quad=ringCorners(points);
      if (quad.length!==4) continue;
      const code=sampleCode(quad,gray,width,height,codes,quietBorderOutliers);
      if (!code) continue;
      const corners=quad.map((_,i) => quad[(i+code.rotation)%4]);
      const area=(cross(quad[0],quad[1],quad[2])+cross(quad[0],quad[2],quad[3]))/2;
      const marker={name:code.name,corners,area};
      if (firstOnly) return [marker];
      if (area > (found.get(code.name)?.area ?? 0)) found.set(code.name, marker);
    }
  }
  return [...found.values()];
}

export function markerLuminance(rgba) {
  const gray=new Uint8Array(rgba.length/4);
  for (let i=0; i<gray.length; i++) gray[i]=(rgba[4*i]+2*rgba[4*i+1]+rgba[4*i+2])/4;
  return gray;
}

export function readDockPattern(rgba, width, height, box, codes) {
  return scanPatterns(markerLuminance(rgba),width,height,box,codes,true,[58,85,108],2)[0]?.name ?? null;
}

export function locatePrintedTiles(gray, width, height, codes) {
  return scanPatterns(gray,width,height,[0,0,width,height],codes,false,[58,85,108],2);
}

export function locateOccludedTiles(gray, width, height, codes) {
  return scanPatterns(gray,width,height,[0,0,width,height],codes,false,[23,30,38,48,58,72,85,108],7);
}
