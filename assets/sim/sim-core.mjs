import loadMujoco from './vendor/mujoco/mujoco.js';
import {SKATE_SURFACES, skateTerrainXml} from './skate-terrain.mjs';
import {SkateTow} from './skate-tow.mjs';

// Runtime packets include mouth motor 34; it has no corresponding MJCF joint.
const RUNTIME_MOTOR_IDS = [10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34];
export const JOINTS = [
  [10, 'left_hip_yaw', 'Left hip yaw'], [11, 'left_hip_roll', 'Left hip roll'],
  [12, 'left_hip_pitch', 'Left hip pitch'], [13, 'left_knee', 'Left knee'], [14, 'left_ankle', 'Left ankle'],
  [20, 'right_hip_yaw', 'Right hip yaw'], [21, 'right_hip_roll', 'Right hip roll'],
  [22, 'right_hip_pitch', 'Right hip pitch'], [23, 'right_knee', 'Right knee'], [24, 'right_ankle', 'Right ankle'],
  [30, 'neck_pitch', 'Neck pitch'], [31, 'head_pitch', 'Head pitch'],
  [32, 'head_yaw', 'Head yaw'], [33, 'head_roll', 'Head roll'],
];
const RAD = Math.PI / 180;

export function parsePose(value, joints) {
  if (!value || value.schema !== 1 || value.robot !== 'xgoduck' || !value.joints_deg || typeof value.joints_deg !== 'object') {
    throw new Error('Choose a Duck Lab pose file (schema 1).');
  }
  const result = {};
  for (const joint of joints) {
    const angle = value.joints_deg[joint.id];
    if (typeof angle !== 'number' || !Number.isFinite(angle) || angle < joint.min - 0.001 || angle > joint.max + 0.001) {
      throw new Error(`Joint ${joint.id} must be between ${joint.min.toFixed(1)}° and ${joint.max.toFixed(1)}°.`);
    }
    result[joint.id] = angle;
  }
  return result;
}

// MuJoCo quaternions are w,x,y,z. Gravity alone cannot determine yaw.
export function attitudeFromGravity(gravity) {
  if (!Array.isArray(gravity) || gravity.length !== 3 || !gravity.every(Number.isFinite)) return null;
  const norm = Math.hypot(...gravity);
  if (norm < 0.1) return null;
  const [x, y, z] = gravity.map(v => v / norm);
  if (z > 0.999999) return [0, 1, 0, 0];
  const q = [1 - z, -y, x, 0];
  const length = Math.hypot(...q);
  return q.map(v => v / length);
}

export class DuckSimulation {
  static async create(readAsset = async path => {
    const response = await fetch(new URL(path, import.meta.url));
    if (!response.ok) throw new Error(`Could not load ${path}: HTTP ${response.status}`);
    return new Uint8Array(await response.arrayBuffer());
  }, {skates = false} = {}) {
    // Download before instantiation: slow links should show the loading screen,
    // rather than trigger Emscripten's periodic "waiting on dependencies" errors.
    const wasmBinary = await readAsset('vendor/mujoco/mujoco.wasm');
    const mj = await loadMujoco({wasmBinary, locateFile: name => new URL(`./vendor/mujoco/${name}`, import.meta.url).href});
    const manifestFile = skates ? 'roller-model-source.json' : 'model-source.json';
    const manifest = JSON.parse(new TextDecoder().decode(await readAsset(manifestFile)));
    const prefix = skates ? '/xgoduck_roller/' : '/xgoduck/';
    const sourceDir = skates ? 'model/roller' : 'model';
    const dir = '/duck';
    mj.FS.mkdir(dir);
    mj.FS.mkdir(`${dir}/assets`);
    const robotFile = skates ? 'robot.xml' : 'robot_allcollisions.xml';
    const paths = manifest.files.map(file => file.path.split(prefix)[1])
      .filter(path => path && (/\.stl$/i.test(path) || path === robotFile));
    paths.push('browser_scene.xml');
    await Promise.all(paths.map(async path => {
      const contents = await readAsset(`${sourceDir}/${path}`);
      const data = skates && path === 'browser_scene.xml'
        ? new TextDecoder().decode(contents).replace('<!-- SKATE TERRAIN -->', skateTerrainXml())
        : contents;
      mj.FS.writeFile(`${dir}/${path}`, data);
    }));
    const model = mj.MjModel.from_xml_path(`${dir}/browser_scene.xml`);
    if (!model) throw new Error('MuJoCo could not compile the Duck model.');
    let data;
    try {
      data = new mj.MjData(model);
      return new DuckSimulation(mj, model, data, skates);
    } catch (error) {
      data?.delete();
      model.delete();
      throw error;
    }
  }

  constructor(mj, model, data, skates) {
    this.mj = mj; this.model = model; this.data = data;
    this.skates = skates;
    this.option = model.opt;
    this.timestep = this.option.timestep;
    this.floor = mj.mj_name2id(model, mj.mjtObj.mjOBJ_GEOM.value, 'floor');
    if (this.floor < 0) throw new Error('Floor geom not found in Duck model.');
    this.wheelCollisions = [];
    this.wheelDofs = [];
    this.surface = 'flat';
    if (skates) {
      for (const side of ['left', 'right']) {
        for (const end of ['front', 'rear']) {
          const geom = mj.mj_name2id(model, mj.mjtObj.mjOBJ_GEOM.value, `${side}_${end}_tire_collision`);
          if (geom < 0) throw new Error('Wheel contact geom not found in Duck model.');
          this.wheelCollisions.push(geom);
        }
      }
      this.wheelDofs = ['LF','LR','RF','RR'].map(name => {
        const joint = mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT.value, `passive_${name}_wheel`);
        if (joint < 0) throw new Error('Passive wheel joint not found.');
        return model.jnt_dofadr[joint];
      });
      this.surfaceContacts = Object.entries(SKATE_SURFACES).map(([name, boxes]) => [
        name, boxes.map(({name}) => mj.mj_name2id(model, mj.mjtObj.mjOBJ_GEOM.value, name)),
      ]);
    }
    this.joints = JOINTS.map(([id, name, label]) => {
      const index = mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT.value, name);
      const actuator = mj.mj_name2id(model, mj.mjtObj.mjOBJ_ACTUATOR.value, name);
      if (index < 0 || actuator < 0) throw new Error(`Missing upstream joint ${name}`);
      return {id, name, label, index, actuator, address: model.jnt_qposadr[index],
        min: model.jnt_range[index * 2] / RAD, max: model.jnt_range[index * 2 + 1] / RAD};
    });
    this.originalGain = model.actuator_gainprm.slice();
    this.originalBias = model.actuator_biasprm.slice();
    this.mode = 'pose'; this.hold = false; this.accumulator = 0; this.skipped = 0;
    this.reset('STAND');
    this.setHold(false);
  }

  reset(preset = 'STAND') {
    if (this.skates && preset === 'STAND') preset = 'home';
    const index = this.mj.mj_name2id(this.model, this.mj.mjtObj.mjOBJ_KEY.value, preset);
    if (index < 0) throw new Error(`Unknown pose: ${preset}`);
    this.mj.mj_resetDataKeyframe(this.model, this.data, index);
    this.tow = null;
    if (this.surface.startsWith('tiles')) this.data.qpos[2] += .003;
    this.targets = this.data.ctrl.slice();
    this.accumulator = 0; this.skipped = 0;
    this.mj.mj_forward(this.model, this.data);
    return this.angles();
  }

  angles() { return Object.fromEntries(this.joints.map(joint => [joint.id, this.data.qpos[joint.address] / RAD])); }
  targetAngles() { return Object.fromEntries(this.joints.map(joint => [joint.id, this.targets[joint.actuator] / RAD])); }

  setJoint(id, angle, {kinematic = this.mode !== 'physics', clamp = true} = {}) {
    const joint = this.joints.find(joint => joint.id === Number(id));
    if (!joint || typeof angle !== 'number' || !Number.isFinite(angle)) throw new Error('Invalid joint angle.');
    const bounded = clamp ? Math.max(joint.min, Math.min(joint.max, angle)) : angle;
    this.targets[joint.actuator] = bounded * RAD;
    this.data.ctrl[joint.actuator] = bounded * RAD;
    if (kinematic) this.data.qpos[joint.address] = bounded * RAD;
    return bounded;
  }

  applyPose(angles, options) {
    for (const joint of this.joints) if (Object.hasOwn(angles, joint.id)) this.setJoint(joint.id, angles[joint.id], options);
    if (this.mode !== 'physics') this.mj.mj_forward(this.model, this.data);
  }

  setHold(hold) {
    this.hold = Boolean(hold);
    this.model.actuator_gainprm.set(this.originalGain);
    this.model.actuator_biasprm.set(this.originalBias);
    if (!this.hold) {
      this.model.actuator_gainprm.fill(0);
      this.model.actuator_biasprm.fill(0);
    }
  }

  setGravity(value) {
    if (!Number.isFinite(value) || value < 0 || value > 20) throw new Error('Invalid gravity.');
    this.option.gravity.set([0, 0, -value]);
  }

  setFriction(value) {
    if (!Number.isFinite(value) || value < 0.05 || value > 3) throw new Error('Invalid floor friction.');
    this.model.geom_friction[this.floor * 3] = value;
    // The upstream tires have higher contact priority than the floor.
    for (const wheel of this.wheelCollisions) this.model.geom_friction[wheel * 3] = value;
  }

  setSurface(surface) {
    if (!this.skates || !Object.hasOwn(SKATE_SURFACES,surface)) throw new Error('Unknown skate surface.');
    this.surface = surface;
    for (const [name, geoms] of this.surfaceContacts) {
      for (const geom of geoms) this.model.geom_conaffinity[geom] = name === surface ? 1 : 0;
    }
    // Approximate rolling losses with a load on each passive axle.
    for (const dof of this.wheelDofs) this.model.dof_damping[dof] = surface === 'carpet' ? .0015 : 0;
  }

  startTow(mount) {
    if (!this.skates) throw new Error('Fit skates before running a tow test.');
    this.reset();
    this.setHold(true);
    this.tow = new SkateTow(this.mj,this.model,this.data,mount);
  }

  drop() {
    this.reset('STAND'); this.mode = 'physics';
    this.data.qpos[2] += 0.08;
    this.mj.mj_forward(this.model, this.data);
  }

  nudge() {
    if (this.mode !== 'physics') return;
    this.data.qvel[0] += 0.18;
    this.data.qvel[3] += 0.45;
  }

  step(count = 1) {
    if (!Number.isInteger(count) || count < 1 || count > 1000) throw new Error('Invalid simulation step count.');
    for (let i = 0; i < count; i++) {
      this.tow?.step(this.timestep);
      this.mj.mj_step(this.model, this.data);
    }
    if (!this.data.qpos.every(Number.isFinite)) throw new Error('Physics state became invalid. Reset the simulation.');
  }

  advance(seconds) {
    this.accumulator += Math.min(0.05, Math.max(0, seconds));
    let steps = 0;
    while (this.accumulator >= this.timestep && steps < 20) {
      this.step(); this.accumulator -= this.timestep; steps++;
    }
    if (this.accumulator >= this.timestep) {
      this.skipped += Math.floor(this.accumulator / this.timestep);
      this.accumulator %= this.timestep;
    }
    return steps;
  }

  applyTelemetry(packet, source = 'targets') {
    if (!packet || !Number.isFinite(packet.feedback_age_ms) || packet.feedback_age_ms > 250 || packet.feedback_age_ms < 0) {
      return {fresh: false, used: 0, measured: 0, imu: false};
    }
    const present = new Set(packet.servo_ids || []);
    const array = source === 'measured' ? packet.angles : packet.targets;
    let used = 0;
    for (const joint of this.joints) {
      const value = array?.[RUNTIME_MOTOR_IDS.indexOf(joint.id)];
      if ((source !== 'measured' || present.has(joint.id)) && typeof value === 'number' && Number.isFinite(value)) {
        this.setJoint(joint.id, value, {kinematic: true, clamp: false}); used++;
      }
    }
    const quaternion = packet.imu_ok ? attitudeFromGravity(packet.gravity) : null;
    if (quaternion) this.data.qpos.set(quaternion, 3);
    this.mj.mj_forward(this.model, this.data);
    return {fresh: true, used, measured: this.joints.filter(joint => present.has(joint.id)).length, imu: Boolean(quaternion)};
  }

  dispose() {
    // MjModel.opt is a borrowed reference to storage owned by MjModel.
    this.data.delete(); this.model.delete();
  }
}
