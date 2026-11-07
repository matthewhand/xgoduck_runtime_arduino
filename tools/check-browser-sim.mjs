import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {DuckSimulation, parsePose, attitudeFromGravity, JOINTS} from '../assets/sim/sim-core.mjs';

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
  assert.equal(sim.applyTelemetry({...packet,feedback_age_ms:500},'targets').fresh,false);
  assert.deepEqual(sim.data.qpos,original,'Stale feedback must freeze the pose');
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
