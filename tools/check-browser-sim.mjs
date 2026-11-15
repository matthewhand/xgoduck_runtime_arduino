import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {DuckSimulation, parsePose, attitudeFromGravity} from '../assets/sim/sim-core.mjs';

const base = new URL('../assets/sim/',import.meta.url);
const read = path => readFile(new URL(path,base));
const lock = JSON.parse(await read('vendor-lock.json'));
for (const file of lock.files) {
  const data = await read(file.path);
  assert.equal(data.length,file.bytes,file.path);
  assert.equal(createHash('sha256').update(data).digest('hex'),file.sha256,file.path);
}
console.log(`PASS: ${lock.files.length} pinned dependency/model checksums`);

const sim = await DuckSimulation.create(read);
try {
  assert.equal(sim.model.nq,21);
  assert.equal(sim.model.nu,14);
  assert.equal(sim.joints.length,14);
  assert.equal(new Set(sim.joints.map(j=>j.address)).size,14);
  assert(!sim.joints.some(j=>j.id===34));
  for (let mesh=0;mesh<sim.model.nmesh;mesh++) {
    const begin=sim.model.mesh_faceadr[mesh]*3;
    const end=begin+sim.model.mesh_facenum[mesh]*3;
    for (const index of sim.model.mesh_face.slice(begin,end)) assert(index>=0&&index<sim.model.mesh_vertnum[mesh]);
  }
  console.log('PASS: real MJCF compiles; 14 distinct motor/joint mappings and valid CAD mesh indices');

  const pose = {schema:1,robot:'xgoduck',joints_deg:sim.targetAngles()};
  assert.deepEqual(parsePose(pose,sim.joints),pose.joints_deg);
  for (const bad of [null,{}, {...pose,schema:2}, {...pose,joints_deg:{...pose.joints_deg,10:NaN}}, {...pose,joints_deg:{...pose.joints_deg,10:1000}}]) {
    assert.throws(()=>parsePose(bad,sim.joints));
  }
  console.log('PASS: pose round trip and invalid/out-of-range import rejection');

  sim.setHold(false);
  assert(sim.model.actuator_gainprm.every(v=>v===0));
  assert(sim.model.actuator_biasprm.every(v=>v===0));
  sim.setGravity(0); sim.drop();
  const zeroHeight=sim.data.qpos[2]; sim.step(25);
  assert(Math.abs(sim.data.qpos[2]-zeroHeight)<1e-6);
  sim.setGravity(9.81); sim.drop();
  assert.equal(sim.mode,'physics');
  const start=sim.data.qpos[2]; sim.step(25);
  assert(sim.data.qpos[2]<start-0.009 && sim.data.qpos[2]>start-0.02);
  sim.step(475);
  assert(sim.data.ncon>0,'Drop must produce actual floor contacts');
  assert(sim.data.qpos[2]>0.02 && sim.data.qpos[2]<0.15,'Robot must not fall through the floor');
  console.log(`PASS: zero-gravity invariance, gravitational fall and floor contacts (${sim.data.ncon})`);

  sim.mode='live'; sim.reset();
  const original=sim.data.qpos.slice();
  const packet={feedback_age_ms:1,servo_ids:[],angles:Array(15).fill(60),targets:Array(15).fill(0),imu_ok:false};
  assert.equal(sim.applyTelemetry(packet,'measured').used,0);
  assert.deepEqual(sim.data.qpos,original,'Missing joints must not become measured zeros/angles');
  const beforeStale=sim.data.qpos.slice();
  assert.equal(sim.applyTelemetry({...packet,feedback_age_ms:500},'targets').fresh,false);
  assert.deepEqual(sim.data.qpos,beforeStale,'Stale feedback must freeze the pose');
  packet.targets[10]=8;
  assert.equal(sim.applyTelemetry(packet,'targets').used,14);
  assert(Math.abs(sim.angles()[30]-8)<1e-6,'Runtime motor 30 must map to neck_pitch');
  assert.equal(sim.angles()[20],0,'Runtime ordering differs from the MJCF chain ordering');
  console.log('PASS: stale/missing feedback and runtime-to-MJCF motor mapping');

  assert.deepEqual(attitudeFromGravity([0,0,-1]),[1,-0,0,0]);
  const q=attitudeFromGravity([0,-1,0]);
  assert(Math.abs(q[0]-Math.SQRT1_2)<1e-9 && Math.abs(q[1]-Math.SQRT1_2)<1e-9);
  assert.equal(attitudeFromGravity([0,0,0]),null);
  assert.equal(attitudeFromGravity([0,NaN,1]),null);
  console.log('PASS: IMU gravity attitude and invalid input handling');
} finally {
  sim.dispose();
}

const skates = await DuckSimulation.create(read, {skates:true});
try {
  assert.equal(skates.model.nq,25);
  assert.equal(skates.model.nu,14);
  skates.setFriction(.7);
  for (const geom of skates.wheelCollisions) assert.equal(skates.model.geom_friction[geom*3], .7);
  const passiveWheels = ['LF','LR','RF','RR'].map(name => {
    const index = skates.mj.mj_name2id(skates.model, skates.mj.mjtObj.mjOBJ_JOINT.value, `passive_${name}_wheel`);
    assert(index >= 0);
    return skates.model.jnt_qposadr[index];
  });
  skates.setHold(true);
  skates.data.qvel[0] = .28;
  skates.step(250);
  assert(skates.data.qpos[0] > .03, 'The skate model should roll forward');
  assert(passiveWheels.every(address => Math.abs(skates.data.qpos[address]) > .5),
    'All four passive wheels must turn under ground load');
  const contacts = new Set();
  const vector = skates.data.contact;
  for (let index = 0; index < skates.data.ncon; index++) {
    const geom = vector.get(index).geom;
    if (geom[0] === skates.floor) contacts.add(geom[1]);
    if (geom[1] === skates.floor) contacts.add(geom[0]);
  }
  assert(skates.wheelCollisions.every(geom => contacts.has(geom)), 'All four tires must contact the floor');
  skates.reset();
  assert(passiveWheels.every(address => skates.data.qpos[address] === 0));
  console.log('PASS: four passive wheels roll on the floor and reset to the upstream skate pose');

  function rollOn(surface) {
    skates.setSurface(surface);
    skates.reset();
    skates.data.qvel[0] = .28;
    const touched = new Set();
    for (let tick = 0; tick < 100; tick++) {
      skates.step(10);
      for (let index = 0; index < skates.data.ncon; index++) {
        for (const id of skates.data.contact.get(index).geom) {
          touched.add(skates.mj.mj_id2name(skates.model,skates.mj.mjtObj.mjOBJ_GEOM.value,id));
        }
      }
    }
    return {distance:skates.data.qpos[0], touched};
  }
  const flat = rollOn('flat');
  assert(![...flat.touched].some(name => /^(tile_|bump_)/.test(name ?? '')));
  assert([...rollOn('tiles').touched].some(name => /^tile_[0-9]/.test(name ?? '')));
  assert([...rollOn('tiles-xl').touched].some(name => /^tile_xl_/.test(name ?? '')));
  assert(rollOn('carpet').distance < flat.distance * .7);
  assert(rollOn('bumps').touched.has('bump_6mm'));
  console.log('PASS: surface switches change floor contact and carpet rolling distance');

  skates.setSurface('flat');
  for (const mount of ['mouth','chassis']) {
    skates.startTow(mount);
    for (let index = 0; index < 45; index++) skates.step(50);
    assert(skates.tow.peak > 0 && skates.tow.peak < 1.5);
    assert.equal(skates.tow.tension,0);
    assert(skates.data.xfrc_applied.every(force => force === 0), 'The tow releases all force');
  }
  console.log('PASS: both tow points receive a bounded force that clears on release');
} finally {
  skates.dispose();
}
