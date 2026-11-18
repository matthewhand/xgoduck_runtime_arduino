import {dockFaces} from './dock-vision-camera.mjs';
import {locatePrintedTiles, markerCodebook} from './dock-pattern.mjs?v=2';

const radians = degrees => degrees*Math.PI/180;
const dot = (a,b) => a[0]*b[0]+a[1]*b[1]+a[2]*b[2];

// The 5-cell ink ring occupies the middle of a 7-cell printed plate.
export function dockReference(layout) {
  const faces=dockFaces(layout), panels=new Map();
  for (const {panel,centre} of faces.filter(face=>face.panel)) {
    const radius=panel.size_m*2.5/7;
    const corners=[[-1,1],[1,1],[1,-1],[-1,-1]].map(([x,y]) =>
      centre.map((v,i)=>v+radius*(x*panel.right[i]+y*panel.up[i])));
    panels.set(panel.name,{corners,normal:panel.normal,centre});
  }
  return {codes:markerCodebook(layout.panels),panels,vertices:faces.flatMap(face=>face.vertices)};
}

function camera(azimuth,elevation,distance) {
  const a=radians(azimuth), e=radians(elevation);
  const ca=Math.cos(a), sa=Math.sin(a), ce=Math.cos(e), se=Math.sin(e);
  const toward=[ce*ca,ce*sa,se], right=[-sa,ca,0], down=[se*ca,se*sa,-ce];
  const eye=toward.map((v,i)=>distance*v+(i===2 ? .04 : 0));
  const project = point => {
    const p=[point[0],point[1],point[2]-.04];
    const depth=distance-dot(toward,p);
    return [dot(right,p)/depth,dot(down,p)/depth];
  };
  return {eye,project};
}

// At each viewing direction solve image translation, focal scale and roll by
// least squares. Only the decoded ring corners and fixed print dimensions enter
// the fit. No replay angles, training boxes or ground-truth pixels enter here.
function fitView(reference,markers,width,azimuth,elevation,distance) {
  const {eye,project}=camera(azimuth,elevation,distance);
  let sx=0,sy=0,su=0,sv=0,ss=0,sp=0,sq=0;
  const points=[];
  for (const marker of markers) {
    const panel=reference.panels.get(marker.name);
    if (dot(eye,panel.normal)<=dot(panel.centre,panel.normal)) return null;
    for (let i=0; i<4; i++) {
      const [x,y]=project(panel.corners[i]), [u,v]=marker.corners[i];
      points.push([x,y,u,v]);
      sx+=x; sy+=y; su+=u; sv+=v;
      ss+=x*x+y*y; sp+=x*u+y*v; sq+=x*v-y*u;
    }
  }
  const n=points.length, variance=ss-(sx*sx+sy*sy)/n;
  if (variance<=0) return null;
  const a=(sp-(sx*su+sy*sv)/n)/variance, b=(sq-(sx*sv-sy*su)/n)/variance;
  const tx=(su-a*sx+b*sy)/n, ty=(sv-b*sx-a*sy)/n;
  let error=0;
  for (const [x,y,u,v] of points) error+=(a*x-b*y+tx-u)**2+(b*x+a*y+ty-v)**2;
  const rms=Math.sqrt(error/n);
  const cost=rms + Math.abs(Math.log(Math.hypot(a,b)/width)) + .35*Math.abs(Math.atan2(b,a));
  return {azimuth,elevation,distance,cost,rms, pixel(point) {
    const [x,y]=project(point);
    return [a*x-b*y+tx,b*x+a*y+ty];
  }};
}

export function locateDock(gray,width,height,reference) {
  const markers=locatePrintedTiles(gray,width,height,reference.codes);
  if (!markers.length) return null;
  let best=null;
  const consider=(az,el,dist)=>{
    if (dist<.12 || el < -15 || el > 90) return;
    const fit=fitView(reference,markers,width,az,el,dist);
    if (fit && (!best || fit.cost<best.cost)) best=fit;
  };
  for (let az=0; az<360; az+=15) for (let el=-10; el<=90; el+=10) {
    for (const dist of [.24,.36,.52]) consider(az,el,dist);
  }
  if (!best) return null;
  for (const [angleStep,distStep] of [[5,.04],[1.5,.015],[.5,.005]]) {
    const {azimuth,elevation,distance}=best;
    for (let i=-2;i<=2;i++) for (let j=-2;j<=2;j++) for (let k=-2;k<=2;k++) {
      consider(azimuth+i*angleStep,elevation+j*angleStep,distance+k*distStep);
    }
  }
  if (best.rms>Math.max(2,.12*Math.sqrt(Math.max(...markers.map(m=>m.area))))) return null;
  const points=reference.vertices.map(best.pixel), xs=points.map(p=>p[0]), ys=points.map(p=>p[1]);
  const bbox=[Math.max(0,Math.min(...xs)),Math.max(0,Math.min(...ys)),
    Math.min(width,Math.max(...xs)),Math.min(height,Math.max(...ys))];
  return {bbox,ids:markers.map(m=>m.name),rms:best.rms};
}
