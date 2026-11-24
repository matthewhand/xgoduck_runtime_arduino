import assert from 'node:assert/strict';
import {benchSnapshot, comparisonRows, readBenchSnapshot} from '../assets/sim/bench-data.mjs';

const packet = {
  mode:'shadow', enabled:false, motors:[10,11,20], servo_ids:[], feedback_hz:99.9, feedback_age_ms:7,
  voltage_v:null, imu_ok:false, gravity:[0,0,-1], acc:[0,0,0], gyro_corrected:[0,0,0],
  mcu_runtime:{imu_seq:0, imu_init_attempts:35, imu_errors:35}, loop_missed:0,
};
const at = '2026-11-24T00:00:00.000Z';
const offline = benchSnapshot(packet, 'revision', at);
assert.deepEqual(offline.servos.missing, [10,11,20]);
assert.equal(offline.controller.torque_enabled, false);
assert.equal(offline.servos.voltage_v, null);
assert.deepEqual([offline.imu.state, offline.imu.tilt_deg, offline.imu.gravity, offline.imu.raw_acc_ms2,
  offline.imu.corrected_gyro_dps], ['offline', null, null, null, null]);
assert.deepEqual(comparisonRows(readBenchSnapshot(JSON.parse(JSON.stringify(offline)))),
  ['Live', 'None detected', 'Offline', '—', 35, 35]);

const online = benchSnapshot({...packet, imu_ok:true, servo_ids:[30,20,10,10], voltage_v:7.8,
  gravity:[.5,0,-Math.sqrt(.75)], acc:[4.9,0,-8.5], mcu_runtime:{imu_seq:14}}, 'revision', at);
assert.deepEqual(online.servos.detected, [10,20,30]);
assert.deepEqual(online.servos.missing, [11]);
assert.deepEqual(online.servos.unexpected, [30]);
assert.equal(online.servos.voltage_v, 7.8);
assert.deepEqual(comparisonRows(online), ['Live', '10, 20, 30', 'Online', '30.0°', '—', '—']);

const stale = benchSnapshot({...packet, enabled:true, imu_ok:true, servo_ids:[10], voltage_v:7.8, feedback_age_ms:150}, null, at);
assert.deepEqual(stale.servos.detected, []);
assert.deepEqual(stale.servos.missing, []);
assert.equal(stale.controller.torque_enabled, null);
assert.equal(stale.imu.state, 'stale');
assert.equal(stale.imu.gravity, null);
assert.equal(stale.servos.voltage_v, null);
assert.equal(benchSnapshot({...packet, servo_ids:null}, null, at).servos.available, false);
assert.throws(() => readBenchSnapshot({schema:1, source:'uno-q-simulation'}), /Bench diagnostics/);
assert.throws(() => benchSnapshot({}), /controller telemetry/);
console.log('PASS: live, offline and stale bench telemetry, servo IDs, IMU tilt and snapshot comparison');
