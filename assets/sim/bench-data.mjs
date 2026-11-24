const FEEDBACK_LIMIT_MS = 150;
const number = value => Number.isFinite(value) ? value : null;
const counter = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
const ids = value => [...new Set(Array.isArray(value) ? value.filter(id => Number.isInteger(id) && id >= 0 && id <= 253) : [])].sort((a,b) => a-b);
const vector = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite) ? value.slice() : null;

export function benchSnapshot(packet, release, capturedAt = new Date().toISOString()) {
  if (!packet || !Array.isArray(packet.motors) || typeof packet.mode !== 'string') {
    throw new Error('The UNO Q did not return controller telemetry.');
  }
  const age = number(packet.feedback_age_ms);
  const fresh = age !== null && age >= 0 && age < FEEDBACK_LIMIT_MS;
  const expected = ids(packet.motors);
  const servoFeedback = fresh && Array.isArray(packet.servo_ids);
  const detected = servoFeedback ? ids(packet.servo_ids) : [];
  const imu = packet.mcu_runtime || {};
  const imuState = !fresh ? 'stale' : packet.imu_ok === true ? 'online' : 'offline';
  const gravity = imuState === 'online' ? vector(packet.gravity) : null;
  const tilt = gravity && Math.hypot(...gravity) > .1
    ? Math.atan2(Math.hypot(gravity[0], gravity[1]), -gravity[2]) * 180 / Math.PI : null;

  return {
    schema:1, source:'duck-lab-bench', captured_at:capturedAt, release:release ?? null,
    controller:{mode:packet.mode, torque_enabled:fresh && typeof packet.enabled === 'boolean' ? packet.enabled : null,
      feedback:fresh ? 'live' : 'stale', feedback_hz:number(packet.feedback_hz), feedback_age_ms:age,
      board_missed_slots:counter(packet.loop_missed), mcu_overruns:counter(packet.mcu_overruns),
      error:typeof packet.last_error === 'string' && packet.last_error ? packet.last_error : null},
    servos:{expected, detected, available:servoFeedback,
      missing:servoFeedback ? expected.filter(id => !detected.includes(id)) : [],
      unexpected:servoFeedback ? detected.filter(id => !expected.includes(id)) : [],
      voltage_v:fresh ? number(packet.voltage_v) : null},
    imu:{state:imuState, sample_sequence:counter(imu.imu_seq), init_attempts:counter(imu.imu_init_attempts),
      errors:counter(imu.imu_errors), calibration_saved:typeof packet.imu_calibration?.calibrated === 'boolean'
        ? packet.imu_calibration.calibrated : null,
      gravity, tilt_deg:tilt, raw_acc_ms2:imuState === 'online' ? vector(packet.acc) : null,
      corrected_gyro_dps:imuState === 'online' ? vector(packet.gyro_corrected) : null},
  };
}

export function readBenchSnapshot(raw) {
  const version = raw && raw.schema === 1 && raw.source === 'duck-lab-bench';
  if (!version || typeof raw.captured_at !== 'string' || !Number.isFinite(Date.parse(raw.captured_at))
      || !['live','stale'].includes(raw.controller?.feedback)
      || !Array.isArray(raw.servos?.detected) || !['online','offline','stale'].includes(raw.imu?.state)) {
    throw new Error('Choose a JSON snapshot exported from Bench diagnostics.');
  }
  return {...raw, servos:{...raw.servos, detected:ids(raw.servos.detected)}};
}

export function comparisonRows(snapshot) {
  const {controller, servos, imu} = snapshot;
  return [
    controller.feedback === 'live' ? 'Live' : 'Stale',
    servos.available === true ? servos.detected.join(', ') || 'None detected' : '—',
    {online:'Online',offline:'Offline',stale:'Stale'}[imu.state],
    imu.state === 'online' && Number.isFinite(imu.tilt_deg) ? `${imu.tilt_deg.toFixed(1)}°` : '—',
    counter(imu.init_attempts) ?? '—',
    counter(imu.errors) ?? '—',
  ];
}
