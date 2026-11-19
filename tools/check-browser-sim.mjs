import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {modPolicyStatus, TRAINED_LAYOUTS} from '../assets/sim/mod-policy.mjs';
import {markerCodebook, readDockPattern} from '../assets/sim/dock-pattern.mjs';
import {CAPTURE_FORMAT, GroveCamera, parseRecording} from '../assets/sim/grove-capture.mjs';
import {differs, frameOutcome} from '../assets/sim/dock-footage.mjs';
import {DuckSimulation, parsePose, attitudeFromGravity} from '../assets/sim/sim-core.mjs';
import {QualificationReplay, SKATE_TURN_LOOP, TURN_SEEK_LOOP, CLEAR_LANE_LOOP, LOWERING_PAIR, RELEASE_PAIR, TRIP_PAIR, mergeDockRecordings, loadDockCase, parseQualificationReport} from '../assets/sim/qualification-replay.mjs';

const base = new URL('../assets/sim/',import.meta.url);
const read = path => readFile(new URL(path,base));
const stockModels = TRAINED_LAYOUTS['v5-stock-feet'];
for (const [role, digest] of Object.entries(stockModels)) {
  const file = await readFile(new URL('../../python/xgoduck_' + role + '.onnx', base));
  assert.equal(createHash('sha256').update(file).digest('hex'), digest);
}
const stockSessions = {loaded_policy_sha256: stockModels};
assert.equal(modPolicyStatus(false, false, stockSessions).state, 'matched');
assert.equal(modPolicyStatus(true, false, stockSessions).state, 'untrained');
assert.equal(modPolicyStatus(false, true, stockSessions).state, 'untrained');
assert.equal(modPolicyStatus(true, true, stockSessions).state, 'untrained');
assert.equal(modPolicyStatus(false, false, null).state, 'offline');
assert.equal(modPolicyStatus(false, false, {active_model: 'xgoduck_walk.onnx'}).state, 'unverified');
for (const [getup, expected] of [[null, 'mismatch'], [stockModels.walk, 'mismatch'], ['unverified', 'unverified']]) {
  assert.equal(modPolicyStatus(false, false, {loaded_policy_sha256: {...stockModels, getup}}).state, expected);
}
assert.equal(modPolicyStatus(false, false, stockSessions, undefined, {teeth: true}).state, 'candidate');
assert.equal(modPolicyStatus(true, false, stockSessions, undefined, {teeth: true}).state, 'untrained');
assert.equal(modPolicyStatus(false, false, stockSessions, undefined, {tusks: true}).state, 'untrained');
assert.equal(modPolicyStatus(false, false, null, undefined, {teeth: true}).state, 'untrained');
assert.equal(modPolicyStatus(false, false, stockSessions, undefined, {tail: true}).state, 'untrained');
assert.equal(modPolicyStatus(false, false, stockSessions, undefined, {tail: true, teeth: true}).state, 'untrained');
assert.equal(modPolicyStatus(false, true, stockSessions, undefined, {tail: true}).state, 'untrained');
const transferred = {...stockModels, transferReport: 'test-report'};
const trained = {...TRAINED_LAYOUTS, 'v5-stock-feet-teeth-r2': transferred};
assert.equal(modPolicyStatus(false, false, stockSessions, trained, {teeth: true}).state, 'transfer');
assert.equal(modPolicyStatus(false, true, stockSessions, trained, {teeth: true}).state, 'untrained');
const harness = JSON.parse(await read('contact-harness.json'));
const carried = [...harness.printed, ...harness.parts, ...harness.leads];
for (const key of ['nominal','low','high']) {
  const mass = carried.reduce((sum, part) => sum + part.mass_g[key], 0);
  assert(Math.abs(mass - harness.estimate.with_printed.mass_g[key]) < .001);
}
for (const lead of harness.leads) {
  const length = lead.points_mm.slice(1).reduce((sum, point, i) =>
    sum + Math.hypot(...point.map((value, axis) => value - lead.points_mm[i][axis])), 0);
  assert(Math.abs(length - lead.length_mm) < .001);
}
console.log('PASS: live policy identities and complete weight layouts');
const {panels} = JSON.parse(await read('dock-vision-layout.json'));
const codes = markerCodebook(panels);
function readFixture(bitmap) {
  const size = 28, pixels = new Uint8Array(size*size*4);
  for (let y=0; y<size; y++) for (let x=0; x<size; x++) {
    const ink = bitmap[Math.floor(y/4)][Math.floor(x/4)] === '1';
    pixels.fill(ink ? 25 : 215,(y*size+x)*4,(y*size+x)*4+3);
  }
  return readDockPattern(pixels,size,size,[0,0,size,size],codes);
}
for (const {name,bitmap} of panels) {
  let bits = bitmap.map(row => [...row]);
  for (let i=0; i<4; i++) {
    assert.equal(readFixture(bits),name);
    bits = bits[0].map((_,x) => bits.map(row=>row[x]).reverse());
  }
}
assert.equal(readFixture(['0000000','0111110','0100010','0100010','0100010','0111110','0000000']),null);
console.log('PASS: all five printed marker IDs in four rotations and an unknown payload');

const jpeg = '/9j/2Q=='; // Minimal framing fixture. Image decoding is checked in the browser.
function fakeGrove(code = 0) {
  const encode = new TextEncoder();
  let stream, open = false;
  const port = {
    async open(options) { assert.equal(options.baudRate,921600); open = true; },
    async close() { assert(open); open = false; },
    readable: new ReadableStream({start(controller) { stream = controller; }}),
    writable: new WritableStream({write(bytes) {
      assert.equal(new TextDecoder().decode(bytes),'AT+SAMPLE=1\r\n');
      stream.enqueue(encode.encode('\r{"type":0,"name":"SAMPLE","code":0}\n\r'));
      stream.enqueue(encode.encode(`{"type":1,"name":"SAMPLE","code":${code},"data":{"ima`));
      stream.enqueue(encode.encode(`ge":"${jpeg}"}}\n`));
    }}),
  };
  return new GroveCamera(port);
}
const grove = fakeGrove();
await grove.open();
assert.equal(await grove.sample(),jpeg);
assert.equal(await grove.sample(),jpeg);
await grove.close();
const rejectedGrove = fakeGrove(4);
await rejectedGrove.open();
await assert.rejects(rejectedGrove.sample(), /SSCMA code 4/);
await rejectedGrove.close();
const clip = {format:CAPTURE_FORMAT,frames:[{t:0,truth:'present',box:[0,0,.5,.5],jpeg},{t:500,truth:'absent',jpeg}]};
assert.deepEqual(parseRecording(clip),clip.frames);
const match = {bbox:[0,0,.5,.5]};
const other = {bbox:[.6,.6,.9,.9]};
assert.equal(frameOutcome(clip.frames[0],match),'hit');
assert.equal(frameOutcome(clip.frames[0],other),'wrong box');
assert.equal(frameOutcome(clip.frames[0],null),'miss');
assert.equal(frameOutcome(clip.frames[1],match),'false alarm');
assert.equal(frameOutcome(clip.frames[1],null),'clear');
assert.equal(frameOutcome({truth:'unknown'},match),'unlabelled');
assert(differs(match,other) && differs(match,null) && !differs(match,match));
assert.throws(() => parseRecording({...clip,frames:[clip.frames[0],clip.frames[0]]}), /timing/);
console.log('PASS: Grove sample transport, recording validation and comparison outcomes');
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

  const dockSources = [
    'floor-dock', 'chair-dock', 'dock-approach', 'contact-dock', 'contact-refinements', 'contact-stress', 'skate-lowering',
    'chair-catch', 'trip-entry', 'clear-lane', 'turn-seek',
  ];
  const recordings = await Promise.all(dockSources.map(async name => JSON.parse(await read(`${name}-recording.json`))));
  const dockReport = mergeDockRecordings(recordings);
  const dockCases = parseQualificationReport(dockReport, sim.joints.map(joint => joint.id));
  const expectedIndex = Object.fromEntries([...dockCases.keys()].map(scenario => [scenario,
    dockSources.filter((_, i) =>
      Object.values(recordings[i]).some(variants => Object.hasOwn(variants, scenario)))]));
  if (process.argv.includes('--write-dock-index')) {
    const entries = Object.entries(expectedIndex).map(([name, sources]) =>
      `  ${JSON.stringify(name)}: ${JSON.stringify(sources)}`);
    await writeFile(new URL('dock-recording-index.json', base), `{\n${entries.join(',\n')}\n}\n`);
  }
  const dockIndex = JSON.parse(await read('dock-recording-index.json'));
  assert.deepEqual(Object.keys(dockIndex), [...dockCases.keys()]);
  assert.deepEqual(dockIndex, expectedIndex, 'Regenerate the index with --write-dock-index.');
  for (const [scenario, cases] of dockCases) {
    const requested = [];
    const selected = await loadDockCase(dockIndex, scenario, source => {
      requested.push(source);
      return recordings[dockSources.indexOf(source)];
    });
    assert.deepEqual(requested, expectedIndex[scenario]);
    assert.deepEqual(Object.keys(selected), [...cases.keys()]);
    for (const name of cases.keys()) assert.equal(selected[name][scenario], dockReport[name][scenario]);
  }
  assert.deepEqual(dockIndex['Skate turnaround trials'], ['turn-seek']);
  console.log(`PASS: ${dockCases.size} docking cases load the same recordings on demand`);
  const centred = dockCases.get('Centred entry');
  const footPad = centred.get('Rails + foot pad');
  assert(footPad.result.passed && footPad.events.has('Foot on pad') && footPad.events.has('Walk again'));
  assert(footPad.result.dock.sideways_mm > 100);
  const wide = dockCases.get('Nearly flat').get('Wide exit channel').result;
  assert(wide.passed && wide.dock.headward_mm < -300 && wide.dock.sideways_mm < 50);
  for (const angle of [30,45]) {
    const ramp = centred.get(`Rails + ${angle}° ramp`);
    assert(ramp.modules.some(module => module.parent === 'world' && module.ramp_deg === angle));
    assert.equal(ramp.result.dock.recovered, false);
  }
  for (const label of ['Low chair', 'Low chair · Skates']) {
    const trial = centred.get(label);
    assert(trial.result.passed && trial.events.has('Chair rise'));
    assert(trial.result.dock.side_tilt_deg < 5 && trial.result.dock.sideways_mm < 10);
    assert(trial.modules.some(module => module.name === 'Backrest' && module.pitch_deg === 45));
  }
  const skating = centred.get('Low chair · Skates');
  assert(skating.events.has('Roll away'));
  assert(skating.result.trace.some(frame => frame.wheels_rad.some(angle => Math.abs(angle) > 1)));
  const approach = dockCases.get('Approach · centred').get('Funnel chair');
  assert(approach.result.trace[0].root[0] >= .3 && approach.events.has('Lower') && approach.events.has('Seated'));
  assert(approach.result.passed && approach.result.dock.side_tilt_deg < 5);
  assert(approach.modules.some(module => module.name === 'Left entry rail' && module.yaw_deg === 14));
  const fast = dockCases.get('Approach · fast');
  assert(!fast.get('Low chair · Skates').result.dock.approach_reached);
  assert(fast.get('Floor-level chair · Skates').result.passed);
  const pads = dockCases.get('Pad approach · centred');
  const feetPads = pads.get('Fixed pad chair').result.dock;
  const skatePads = pads.get('Fixed pad chair · Skates, later tuck').result.dock;
  assert(feetPads.pads_loaded && feetPads.side_tilt_deg < 25);
  assert(skatePads.pads_loaded && skatePads.backrest_deg === feetPads.backrest_deg);
  assert(feetPads.seat_trigger_m > skatePads.seat_trigger_m);
  assert(Object.values(skatePads.contact_force_n).every(force => force > 1));
  const refinedName = 'Fixed pad chair · Wider pads and skate roll-off';
  for (const entry of ['centred', 'left', 'right', 'yaw left', 'yaw right']) {
    const trial = dockCases.get(`Pad approach · ${entry}`).get(refinedName);
    const result = trial.result.dock;
    assert(trial.result.passed && result.roller_release.wheels_only_exit);
    assert(result.contact_force_n.Left >= 2 && result.contact_force_n.Right >= 2);
    assert(trial.events.has('Seated') && trial.events.has('Roll away'));
  }
  console.log('PASS: docking replay includes the approach, seating, chair rise, and independent wheel motion');

  const stress = dockCases.get('Skate approach · 0.32 m/s · centred');
  const distance = stress.get('Skate stress · Distance handoff');
  const clearance = stress.get('Skate stress · Clearance handoff');
  assert(distance.result.dock.pads_loaded && !distance.events.has('Roll away') && !distance.result.passed);
  assert(clearance.events.has('Roll away') && clearance.result.passed);
  assert(clearance.result.dock.roller_release.chair_clearance_mm >= 3);
  assert(clearance.result.dock.roller_release.after_handoff_m >= .15);
  const angled = dockCases.get('Seated restart · 10 s · angled left').get('Skate stress · Clearance handoff');
  assert(angled.result.dock.pads_loaded && !angled.result.passed);
  console.log('PASS: skate stress replay preserves the failed distance check, successful clearance check, and hard restart');

  const lowering = dockCases.get('Slow skate approach · 0.22 m/s · centred');
  const [before, after] = LOWERING_PAIR.map(name => lowering.get(name));
  assert(before.result.dock.pads_loaded && !before.result.passed && after.result.passed);
  assert(after.events.get('Lower') > before.events.get('Lower'));
  assert(after.events.get('Roll away') > after.events.get('Seated'));
  for (const angle of [20,25,30]) {
    const {modules} = lowering.get(`Controlled · ${angle}° lip`);
    const lip = modules.find(module => module.name === 'Seat lip');
    const flatLip = before.modules.find(module => module.name === lip.name);
    assert.equal(lip.ramp_deg, angle);
    assert.equal(lip.center_m[0], flatLip.center_m[0]);
    assert(Math.abs(lip.size_m[2] - flatLip.size_m[2] - .018*Math.tan(angle*Math.PI/180)) < 1e-10);
    assert(modules.filter(module => module.name.endsWith('seat contact')).every(module => module.pitch_deg === -angle));
  }
  console.log('PASS: paired slow skate replay and correctly inclined lips and pads');

  const releaseTrial = dockCases.get('Skate release · 20° lip · 0.32 m/s · centred');
  const [clearanceCheck, contactCheck] = RELEASE_PAIR.map(name => releaseTrial.get(name));
  assert(clearanceCheck.result.dock.pads_loaded && !clearanceCheck.events.has('Roll away'));
  assert(contactCheck.result.passed && contactCheck.events.has('Roll away'));
  assert(contactCheck.result.dock.roller_release.chair_clearance_mm < 0);
  assert.deepEqual(contactCheck.result.dock.roller_release.exit_chair_contacts, []);
  const recess = dockCases.get('Recess trial · 0.28 m/s · 20 mm left');
  assert(recess.get('Flat seat').result.passed && !recess.get('Raised sides · 5 mm').result.passed);
  assert.equal(recess.get('Raised sides · 5 mm').modules.filter(module => module.name.endsWith('seat guide')).length, 2);
  console.log('PASS: skating from a free upright stance and recess trial with both side ramps');

  const bar = dockCases.get('Trip bar · 6 mm · centred');
  const [trip, stepOver] = TRIP_PAIR.map(name => bar.get(name));
  assert(trip.events.get('Foot caught') >= trip.events.get('Lean back'));
  assert(trip.events.get('Seated') > trip.events.get('Foot caught') && trip.result.dock.pads_loaded);
  assert(!trip.result.passed && !trip.result.dock.bar_entry.dock_and_exit);
  assert(stepOver.events.get('Right step') > stepOver.events.get('Left step'));
  assert(!stepOver.events.has('Seated') && !stepOver.result.dock.bar_entry.clean_step);
  assert(stepOver.result.dock.bar_entry.bar_hit_during_step);
  for (const trial of [trip, stepOver]) {
    assert.deepEqual(trial.modules.find(m => m.name === 'Trip bar').size_m, [.008, .22, .006]);
  }
  assert(bar.get('Skates · Coast beside short bar').result.passed);
  assert(bar.get('Feet · Clear lane').result.passed && bar.get('Skates · Clear lane').result.passed);
  console.log('PASS: foot trip, failed skate step-over and successful clear-lane departures');

  const qualification = dockCases.get('Clear lane · 100 approaches per footwear');
  assert.deepEqual([...qualification.keys()], CLEAR_LANE_LOOP);
  for (const name of CLEAR_LANE_LOOP) {
    const trial = qualification.get(name);
    const {dock, passed} = trial.result;
    assert.equal(passed, name.endsWith('Success'));
    assert.equal(dock.qualification.outcome === 'Clean exit', passed);
    assert.equal(dock.qualification.cohort_clean, dock.skates ? 49 : 54);
    assert(!trial.modules.some(module => module.name === 'Trip bar'));
  }
  const playlist = {
    time:1, duration:1, alternating:true, playlist:CLEAR_LANE_LOOP, selected:CLEAR_LANE_LOOP[0],
    get:() => ({value:1}), select(name) { this.selected = name; },
  };
  for (const expected of [...CLEAR_LANE_LOOP.slice(1), CLEAR_LANE_LOOP[0]]) {
    QualificationReplay.prototype.advance.call(playlist, 1, true);
    assert.equal(playlist.selected, expected);
  }
  console.log('PASS: 200-trial qualification samples and four-clip playback wraparound');

  const turns = dockCases.get('Turn around and seek backwards');
  for (const name of TURN_SEEK_LOOP.slice(0, 2)) {
    const clip = turns.get(name);
    assert(clip.result.passed && clip.events.get('Seek backwards') > clip.events.get('Turn around'));
    assert(clip.result.dock.navigation.reverse_m > .17 && clip.events.get('Seated') > clip.events.get('Seek backwards'));
  }
  const skateTurns = dockCases.get('Skate turnaround trials');
  for (const name of SKATE_TURN_LOOP) {
    const clip = skateTurns.get(name);
    assert(clip.result.dock.skates && !clip.events.has('Seated') && !clip.events.has('Seek backwards'));
    assert.equal(clip.result.dock.navigation.cohort.total, 9);
    assert.equal(clip.result.dock.navigation.cohort.ready, 0);
  }
  const arc = skateTurns.get('Rolling arc · Anticlockwise');
  assert(arc.events.has('Slow for reverse') && arc.result.dock.navigation.cohort.held === 9);
  assert(arc.result.dock.navigation.speed_at_heading > .12);
  console.log('PASS: walking turn/reverse sequence and matched skate pivot and rolling-arc replays');

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
