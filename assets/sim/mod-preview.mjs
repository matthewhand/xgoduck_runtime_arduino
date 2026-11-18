import * as THREE from 'three';

async function readDrawing(name) {
  const response = await fetch(new URL(name, import.meta.url));
  if (!response.ok) throw new Error('Could not load V5 backpack drawing ' + name);
  return response.json();
}

const printPoint = ([x, y, z]) => new THREE.Vector3(
  (z - 57.33226) / 1000, (x - .00628) / 1000, (y - 39.25512) / 1000,
);
const materials = {
  'pad-a': '#edc97e', 'pad-b': '#edc97e', 'keyed-isolator': '#9c79c2',
  'disconnect-pack': '#f3edce', 'disconnect-carrier': '#96c4b1', 'plug-envelope': '#777f8b',
  'relief-pack': '#70868e', 'relief-carrier': '#70868e',
};

function makeHarness(drawing) {
  const harness = new THREE.Group();
  harness.name = 'harness';
  const up = new THREE.Vector3(0, 1, 0);
  const r = drawing.wire.jacket_od_mm / 2000;
  const joint = new THREE.SphereGeometry(r, 10, 8);
  for (const lead of drawing.leads) {
    const material = new THREE.MeshStandardMaterial({color: lead.pole === 'A' ? '#ef7b43' : '#4ca6d9'});
    const pts = lead.points_mm.map(printPoint);
    for (let i = 0; i < pts.length; i++) {
      const cap = new THREE.Mesh(joint, material);
      cap.position.copy(pts[i]);
      harness.add(cap);
      if (!i) continue;
      const direction = pts[i].clone().sub(pts[i - 1]);
      const cylinder = new THREE.CylinderGeometry(r, r, direction.length(), 10);
      const segment = new THREE.Mesh(cylinder, material);
      segment.position.copy(pts[i - 1]).lerp(pts[i], .5);
      segment.quaternion.setFromUnitVectors(up, direction.normalize());
      harness.add(segment);
    }
  }
  for (const part of drawing.parts) {
    const [x, y, z] = part.size_mm;
    const geometry = new THREE.BoxGeometry(z / 1000, x / 1000, y / 1000);
    const material = new THREE.MeshStandardMaterial({color: materials[part.id] || '#b2baca'});
    const component = new THREE.Mesh(geometry, material);
    component.name = part.id;
    component.position.copy(printPoint(part.center_mm));
    harness.add(component);
  }
  return harness;
}

export async function loadModPreview() {
  const [shapes, harness] = await Promise.all([readDrawing('./v5-top-entry.json'), readDrawing('./contact-harness.json')]);
  const group = new THREE.Group();
  group.userData.harness = harness;
  const colors = {housing: '#719393', rails: '#63c6b6', cover: '#e5ac64'};
  for (const [name, color] of Object.entries(colors)) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(shapes[name].positions_mm, 3));
    geometry.setIndex(shapes[name].indices);
    geometry.scale(.001, .001, .001);
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({color, roughness: .72, flatShading: true});
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = name;
    group.add(mesh);
  }
  group.add(makeHarness(harness));
  group.visible = false;
  return group;
}

export function showModLayers(group, pack, trace) {
  for (const name of ['rails', 'cover', 'harness']) group.getObjectByName(name).visible = pack;
  const tracing = pack && trace;
  for (const name of ['housing', 'cover', 'rails']) {
    const material = group.getObjectByName(name).material;
    material.transparent = tracing;
    material.opacity = tracing ? .18 : 1;
    material.depthWrite = !tracing;
    material.needsUpdate = true;
  }
  // Draw the continuous harness even where the walking-model trunk obscures the carrier.
  group.getObjectByName('harness').traverse(mesh => {
    if (!mesh.material) return;
    mesh.renderOrder = tracing ? 2 : 0;
    mesh.material.depthTest = !tracing;
  });
}
