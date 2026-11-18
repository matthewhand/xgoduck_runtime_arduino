import * as THREE from 'three';

// These colour previews use the walking-model shells. The printable masks are
// clipped to the registered V5 panel outlines in the hardware generator.
const cache = new Map();
const colors = {feather: '#65c9a6', orbit: '#eab362', chevron: '#e48f82'};
const panel = /^(head_roll|trunk_base|(?:left|right)_hip_pitch)$/;

function makeTexture(pattern) {
  if (cache.has(pattern)) return cache.get(pattern);
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 512;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#384856';
  ctx.fillRect(0, 0, 512, 512);
  ctx.save();
  ctx.beginPath(); ctx.roundRect(28, 36, 456, 440, 52); ctx.clip();
  ctx.translate(256, 256); ctx.scale(9, -9);
  ctx.lineCap = ctx.lineJoin = 'round';
  ctx.strokeStyle = ctx.fillStyle = colors[pattern];
  function line(points, width) {
    ctx.lineWidth = width; ctx.beginPath(); ctx.moveTo(...points[0]);
    for (const point of points.slice(1)) ctx.lineTo(...point);
    ctx.stroke();
  }
  for (let row = -3; row <= 3; row++) {
    for (let col = -3; col <= 3; col++) {
      const [sx, sy] = pattern === 'feather' ? [13, 19] : pattern === 'orbit' ? [17, 16] : [14, 12];
      ctx.save(); ctx.translate((col + Math.abs(row % 2) * .5) * sx, row * sy);
      if (pattern === 'feather') {
        line([[-2,-7],[-.8,-2],[0,2],[1.7,7.2]], 1);
        for (const y of [-4,-.5,3]) {
          const x = y * .25;
          line([[x,y],[x-2.8,y+1.6],[x-4.5,y+4]], 1);
          line([[x,y],[x+2.4,y+.8],[x+4.3,y+2.8]], 1);
        }
      } else if (pattern === 'orbit') {
        const stars = [[-5,-3],[-1,3],[3.5,2],[5,6]];
        line(stars, .9); line([[-5,-3],[.5,-5],[3.5,2]], .9);
        for (const [i, [x,y]] of stars.entries()) {
          ctx.beginPath(); ctx.arc(x,y,[1.3,1.65,1,1.15][i],0,2*Math.PI); ctx.fill();
        }
        ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(4.5,-5,1.6,0,2*Math.PI); ctx.stroke();
      } else {
        for (const y of [-3,.3]) line([[-5,-1+y],[0,3+y],[5,-1+y]], 1.2);
        line([[-2,-5],[0,-3.4],[2,-5]], 1.1);
      }
      ctx.restore();
    }
  }
  ctx.restore();
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  cache.set(pattern, texture);
  return texture;
}

function ensurePanelUV(geometry) {
  if (geometry.hasAttribute('uv')) return;
  geometry.computeBoundingBox();
  const box = geometry.boundingBox;
  const size = box.getSize(new THREE.Vector3()).toArray();
  const axes = [0, 1, 2].sort((a, b) => size[b] - size[a]);
  const min = box.min.toArray();
  const positions = geometry.getAttribute('position');
  const uv = new Float32Array(2 * positions.count);
  for (let i = 0; i < positions.count; i++) {
    for (let k = 0; k < 2; k++) {
      const axis = axes[k];
      uv[2*i+k] = (positions.getComponent(i, axis) - min[axis]) / Math.max(size[axis], 1e-9);
    }
  }
  geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
}

export function setShellSkin(visualMeshes, sim, pattern) {
  for (const mesh of visualMeshes) {
    const {geom, meshName} = mesh.userData;
    const name = meshName || sim.mj.mj_id2name(sim.model, sim.mj.mjtObj.mjOBJ_MESH.value, sim.model.geom_dataid[geom]);
    if (!panel.test(name)) continue;
    const mat = mesh.material;
    if (!(pattern in colors)) {
      if (!mesh.userData.beforeSkin) continue;
      mat.color.copy(mesh.userData.beforeSkin.color);
      mat.map = mesh.userData.beforeSkin.map;
      delete mesh.userData.beforeSkin;
    } else {
      mesh.userData.beforeSkin ??= {color: mat.color.clone(), map: mat.map};
      ensurePanelUV(mesh.geometry);
      mat.color.set(0xffffff);
      mat.map = makeTexture(pattern);
    }
    mat.needsUpdate = true;
  }
}
