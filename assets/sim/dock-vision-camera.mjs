/* Pinhole camera for the browser orbit. The layout is the same one used by
 * the printable tile generator. The depth buffer resolves tiles, chair,
 * seat contacts and occluding faces before the frame reaches the detector. */
const add = (a, b) => a.map((v, i) => v + b[i]);
const sub = (a, b) => a.map((v, i) => v - b[i]);
const scale = (a, s) => a.map(v => v * s);
const dot = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const unit = a => scale(a, 1 / Math.hypot(...a));

function prism(profile, width, center, color) {
  const near = profile.map(([x, z]) => add([x, -width/2, z], center));
  const far = profile.map(([x, z]) => add([x, width/2, z], center));
  const polygons = [near, far, ...near.map((point, i) => {
    const next = (i+1) % near.length;
    return [point, near[next], far[next], far[i]];
  })];
  const centre = scale([...near,...far].reduce(add, [0,0,0]), 1/(2*near.length));
  return polygons.map(vertices => {
    let normal = unit(cross(sub(vertices[1],vertices[0]), sub(vertices[2],vertices[0])));
    if (dot(normal,sub(vertices[0],centre)) < 0) normal = scale(normal,-1);
    return {vertices, normal, color};
  });
}

export function dockFaces(layout) {
  const body = [104,124,148];
  const faces = prism(layout.wedge.profile_xz_m,layout.wedge.width_m,[0,0,0],body);
  for (const part of layout.boxes) {
    const [x,y,z] = scale(part.size_m,.5);
    faces.push(...prism([[-x,-z],[x,-z],[x,z],[-x,z]],2*y,part.center_m,
      part.material === 'contact' ? [183,147,88] : body));
  }
  for (const panel of layout.panels) {
    const centre = add(panel.center_m,scale(panel.normal,layout.plate_thickness_m + layout.ink_thickness_m));
    const vertices = [[-1,-1],[1,-1],[1,1],[-1,1]].map(([x,y]) =>
      add(centre, add(scale(panel.right,x*panel.size_m/2),scale(panel.up,y*panel.size_m/2))));
    faces.push({vertices, normal:panel.normal, color:body, panel, centre});
  }
  return faces;
}

export function renderDockView(faces, azimuth, elevation, marked, width, height) {
  const az = azimuth*Math.PI/180, el = elevation*Math.PI/180;
  const direction = [-Math.cos(el)*Math.cos(az),-Math.cos(el)*Math.sin(az),-Math.sin(el)];
  const right = [-Math.sin(az),Math.cos(az),0], up = cross(right,direction);
  const eye = sub([-.006,0,.040],scale(direction,.30));
  const focal = width, cx = width*.5, cy = height*.5;
  const depth = new Float32Array(width*height).fill(Infinity);
  const rgba = new Uint8ClampedArray(width*height*4);
  for (let y=0; y<height; y++) for (let x=0; x<width; x++) {
    const isGrout = (x + Math.floor(y*.32))%22 === 0 || y%24 === 0;
    const base = 149 + y*.16 - x*.08 - (isGrout ? 12 : 0);
    const i = 4*(x+y*width);
    rgba[i]=base; rgba[i+1]=base+2; rgba[i+2]=base-2; rgba[i+3]=255;
  }
  const bbox = [width,height,0,0];
  for (const face of faces) {
    if (dot(face.normal,sub(eye,face.vertices[0])) <= 0) continue;
    const vertices = face.vertices.map(vertex => {
      const rel = sub(vertex,eye);
      const z = dot(rel,direction);
      return [cx+focal*dot(rel,right)/z, cy-focal*dot(rel,up)/z];
    });
    const minX = Math.max(0,Math.floor(Math.min(...vertices.map(v=>v[0]))));
    const maxX = Math.min(width,Math.ceil(Math.max(...vertices.map(v=>v[0]))));
    const minY = Math.max(0,Math.floor(Math.min(...vertices.map(v=>v[1]))));
    const maxY = Math.min(height,Math.ceil(Math.max(...vertices.map(v=>v[1]))));
    const plane = dot(face.normal,sub(face.vertices[0],eye));
    const shade = .68+.32*Math.max(0,dot(face.normal,[.45,-.45,.77]));
    for (let y=minY; y<maxY; y++) for (let x=minX; x<maxX; x++) {
      const px=x+.5, py=y+.5;
      let positive=false, negative=false;
      for (let n=0; n<vertices.length; n++) {
        const [ax,ay]=vertices[n], [bx,by]=vertices[(n+1)%vertices.length];
        const v=(bx-ax)*(py-ay)-(by-ay)*(px-ax);
        if (v>0) positive=true;
        if (v<0) negative=true;
        if (positive && negative) break;
      }
      if (positive && negative) continue;
      const ray=add(direction,add(scale(right,(px-cx)/focal),scale(up,(cy-py)/focal)));
      const dist=plane/dot(ray,face.normal), idx=y*width+x;
      if (dist<=0 || dist>=depth[idx]) continue;
      depth[idx]=dist;
      let color=face.color;
      if (marked && face.panel) {
        const {panel}=face, hit=sub(add(eye,scale(ray,dist)),face.centre);
        const cell=value=>Math.max(0,Math.min(panel.bitmap.length-1,Math.floor(value*panel.bitmap.length)));
        const col=cell(.5+dot(hit,panel.right)/panel.size_m);
        const row=cell(.5-dot(hit,panel.up)/panel.size_m);
        color=panel.bitmap[row][col]==='1' ? [28,28,28] : [220,220,214];
      }
      for (let channel=0;channel<3;channel++) rgba[idx*4+channel]=shade*color[channel];
      bbox[0]=Math.min(bbox[0],x); bbox[1]=Math.min(bbox[1],y);
      bbox[2]=Math.max(bbox[2],x+1); bbox[3]=Math.max(bbox[3],y+1);
    }
  }
  return {rgba,bbox};
}
