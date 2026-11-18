import * as THREE from 'three';

const q0 = new THREE.Quaternion(), q1 = new THREE.Quaternion();
const roles = value => Array.isArray(value) && value.every(name => typeof name === 'string') &&
  new Set(value).size === value.length;
const finite = (values, size) => Array.isArray(values) && values.length === size && values.every(Number.isFinite);

// Read measured root, joint and hinge poses in the same simulation clock.
// Frames contain MuJoCo w,x,y,z quaternions, while Three.js uses x,y,z,w.
export class TailRecording {
  constructor(record) {
    const {joint_names: joints, hinge_names: hinges, frames} = record;
    if (!roles(joints) || joints.length !== 14 || !roles(hinges) || !hinges.length ||
        !Array.isArray(frames) || frames.length < 2 ||
        frames.some((p,i) => !Number.isFinite(p.t) || (i && p.t <= frames[i-1].t) ||
          !finite(p.root,7) || !finite(p.joints,joints.length) || !finite(p.hinges,hinges.length) ||
          Math.abs(Math.hypot(...p.root.slice(3)) - 1) > .005)) {
      throw new Error('Tail recording has invalid pose samples.');
    }
    this.frames = frames;
    this.joints = joints;
    this.hinges = hinges;
    this.duration = frames.at(-1).t - frames[0].t;
  }

  apply(sim, seconds, setHinge) {
    if (this.sim !== sim) {
      this.address = this.joints.map(name => {
        const joint = sim.joints.find(j => j.name === name);
        if (!joint) throw new Error('The tail recording uses an incompatible joint map.');
        return joint.address;
      });
      this.sim = sim;
    }
    const time = this.frames[0].t + seconds % this.duration;
    let low = 0, high = this.frames.length - 1;
    while (high - low > 1) {
      const mid = (low + high) >> 1;
      if (time < this.frames[mid].t) high = mid; else low = mid;
    }
    const a = this.frames[low], b = this.frames[high];
    const fraction = (time - a.t) / (b.t - a.t);
    const mix = (x, y) => x + (y - x) * fraction;
    const q = sim.data.qpos;
    for (let i = 0; i < 3; i++) q[i] = mix(a.root[i], b.root[i]);
    q0.set(a.root[4], a.root[5], a.root[6], a.root[3]).normalize();
    q1.set(b.root[4], b.root[5], b.root[6], b.root[3]).normalize();
    q0.slerp(q1, fraction);
    q[3] = q0.w; q[4] = q0.x; q[5] = q0.y; q[6] = q0.z;
    for (let i = 0; i < this.joints.length; i++) q[this.address[i]] = mix(a.joints[i], b.joints[i]);
    for (let i = 0; i < this.hinges.length; i++) setHinge(this.hinges[i], mix(a.hinges[i], b.hinges[i]));
    sim.mj.mj_forward(sim.model, sim.data);
  }
}
