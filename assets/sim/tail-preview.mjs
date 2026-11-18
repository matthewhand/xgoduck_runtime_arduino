import * as THREE from 'three';
import {TailRecording} from './tail-recording.mjs';

const colors = {mount:'#8a9a8b', proximal:'#8ac2b0', distal:'#c4915e'};
const pitch = 'passive_tail_pitch', yaw = 'passive_tail_yaw';
const vec = ([x,y,z]) => new THREE.Vector3(z,x,y);
const datum = new THREE.Vector3(.05733226,.00000628,.03925512);
const point = xyz => vec(xyz).multiplyScalar(.001).sub(datum);

async function readAsset(path) {
  const response = await fetch(new URL(path,import.meta.url));
  if (!response.ok) throw new Error('Could not load ' + path + ' from Duck Lab.');
  return response.json();
}

export async function loadTailPreview() {
  const drawing = await readAsset('./v5-raptor-tail.json');
  const group = new THREE.Group();
  const groups = {mount: group};
  const origins = {mount: new THREE.Vector3()};
  const hinges = {};
  for (const joint of drawing.joints) {
    const parent = groups[joint.parent];
    if (!parent || !['proximal','distal'].includes(joint.child))
      throw new Error('Unexpected parent or child in the tail drawing.');
    const pivot = new THREE.Group();
    const origin = point(joint.origin_mm);
    pivot.position.copy(origin).sub(origins[joint.parent]);
    parent.add(pivot);
    groups[joint.child] = pivot;
    origins[joint.child] = origin;
    hinges[joint.child === 'proximal' ? pitch : yaw] = {pivot, axis:vec(joint.axis).normalize()};
  }
  for (const record of drawing.meshes) {
    const geometry = new THREE.BufferGeometry();
    const {positions_mm:positions,indices} = record;
    const vertices = new Float32Array(positions.length);
    for (let i = 0; i < vertices.length; i += 3) {
      const vertex = point([positions[i],positions[i+1],positions[i+2]]).sub(origins[record.group]);
      vertex.toArray(vertices,i);
    }
    geometry.setAttribute('position', new THREE.BufferAttribute(vertices,3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: colors[record.group], flatShading:true, roughness:.68,
    }));
    mesh.name = record.name;
    groups[record.group].add(mesh);
  }
  const setHinge = (name, radians) => {
    const {pivot,axis} = hinges[name];
    pivot.quaternion.setFromAxisAngle(axis,radians);
  };
  let recording, trialText;
  try {
    const trial = await readAsset('./tail-motion.json?v=45a64b28');
    recording = new TailRecording(trial);
    if (!(recording.hinges.length === 2 && recording.hinges.every(name => Object.hasOwn(hinges,name))))
      throw new Error('Tail recording and assembly use different hinges.');
    const pitchRange = recording.frames.map(frame => frame.hinges[recording.hinges.indexOf(pitch)] * 180 / Math.PI);
    const yawRange = recording.frames.map(frame => Math.abs(frame.hinges[recording.hinges.indexOf(yaw)]) * 180 / Math.PI);
    trialText = 'Recorded stock-feet walk · ' + recording.duration.toFixed(1) + ' s. Mean tail pitch ' +
      Math.round(pitchRange.reduce((sum, angle) => sum + angle, 0) / pitchRange.length) +
      '°. Peak yaw ' + Math.max(...yawRange).toFixed(1) + '°. Both hinges move passively.';
  } catch {
    recording = null;
    trialText = 'Static fit preview. Matching tail motion data is unavailable.';
  }
  const mass = drawing.estimate.with_printed.mass_g;
  const massText = 'Tail backpack · ' + mass.nominal.toFixed(1) + ' g estimated (' +
    mass.low.toFixed(1) + '–' + mass.high.toFixed(1) + ' g) including enclosure rails and fasteners. NFC tag excluded.';
  return {
    group, trialText, hasTrace:Boolean(recording),
    massText,
    play(sim,seconds) { recording?.apply(sim,seconds,setHinge); },
    rest() { for (const name of Object.keys(hinges)) setHinge(name,0); },
  };
}
