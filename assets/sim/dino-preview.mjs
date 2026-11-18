import * as THREE from 'three';

const colors = {
  'head-shell': '#84968b', 'head-hardware': '#404f55',
  'head-bottom': '#69978c', 'lower-jaw': '#598477',
  'upper-pad': '#526264', 'lower-pad': '#526264',
  'upper-teeth': '#f3deaa', 'lower-teeth': '#f7e9bf',
  'upper-tusks': '#edbc70', 'upper-teeth-tusks': '#f4da9b',
};

async function asset(path) {
  const response = await fetch(new URL(path, import.meta.url));
  if (!response.ok) throw new Error('Could not load the V5 beak drawing');
  return response;
}

export async function loadDinoPreview() {
  const [metadata, binary] = await Promise.all([
    asset('./dino-head.json?v=100dc190').then(response => response.json()),
    asset('./dino-head.bin?v=d359fd43').then(response => response.arrayBuffer()),
  ]);
  const group = new THREE.Group();
  const hinge = new THREE.Group();
  hinge.name = 'jaw-hinge';
  hinge.position.fromArray(metadata.hinge_mm).multiplyScalar(.001);
  group.add(hinge);

  for (const record of metadata.meshes) {
    const raw = new Int16Array(binary, record.position_offset, record.vertices * 3);
    const indices = new Uint16Array(binary, record.index_offset, record.indices);
    const position = Float32Array.from(raw, value => value / metadata.units_per_metre);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(position, 3));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({color: colors[record.name], roughness: .74});
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = record.name;
    mesh.userData.variant = record.variant;
    if (record.name === 'head-shell') mesh.userData.meshName = 'head_roll';
    if (record.group === 'moving') {
      mesh.position.copy(hinge.position).negate();
      hinge.add(mesh);
    } else {
      group.add(mesh);
    }
  }
  group.userData.replacesHeadRoll = true;
  group.userData.massByVariant = metadata.mass_by_variant_g;
  group.userData.hinge = hinge;
  group.visible = false;
  return group;
}

export function updateDinoPreview(group, elapsedSeconds, {teeth, tusks}) {
  const upper = teeth && tusks ? 'teeth-tusks' : teeth ? 'teeth' : tusks ? 'tusks' : null;
  group.traverse(mesh => {
    const variant = mesh.userData.variant;
    if (!variant || variant === 'all') return;
    mesh.visible = mesh.name === 'lower-teeth' ? Boolean(teeth) : variant === upper;
  });
  // The walking-model head-roll joint has no actuated bite. This is a rigid
  // playback on a second, measured horn axis in the replacement visual.
  const phase = (1 - Math.cos(elapsedSeconds * 2 * Math.PI / 3.2)) * .5;
  group.userData.hinge.rotation.x = teeth ? -THREE.MathUtils.degToRad(26) * phase : 0;
}
