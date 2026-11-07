import * as THREE from 'three';
import {OrbitControls} from './vendor/three/OrbitControls.js';
import {DuckSimulation, parsePose} from './sim-core.mjs';

const $ = id => document.getElementById(id);
const viewport = $('viewport');
let sim, renderer, orbit, camera, scene;
let mode = 'pose', running = false, gait = false, gaitTime = 0, selected = 32;
let lastPacket = null, lastPacketAt = 0, liveResult = null, stopping = false;
let previousFrame = 0, fpsStart = 0, fpsFrames = 0, fps = 0, lastHud = 0;
const geometryCache = new Map(), visualMeshes = [], collisionMeshes = [], jointMarkers = [];
const rows = new Map();
const matrix = new THREE.Matrix4();
const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();

function showError(error) {
  $('error').hidden = false;
  $('error').textContent = error.message || String(error);
}

function resetCamera() {
  camera.position.set(0.36, -0.43, 0.28);
  orbit.target.set(0.012, 0, 0.145);
  orbit.update();
}

function makeGeometry(id) {
  if (geometryCache.has(id)) return geometryCache.get(id);
  const model = sim.model;
  const vertexStart = model.mesh_vertadr[id] * 3, vertexCount = model.mesh_vertnum[id] * 3;
  const faceStart = model.mesh_faceadr[id] * 3, faceCount = model.mesh_facenum[id] * 3;
  const positions = new Float32Array(model.mesh_vert.slice(vertexStart, vertexStart + vertexCount));
  const indices = new Uint32Array(model.mesh_face.slice(faceStart, faceStart + faceCount));
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  geometry.computeVertexNormals(); geometry.computeBoundingSphere();
  geometryCache.set(id, geometry);
  return geometry;
}

function buildRobot() {
  const model = sim.model;
  for (let geom = 0; geom < model.ngeom; geom++) {
    if (model.geom_type[geom] !== sim.mj.mjtGeom.mjGEOM_MESH.value) continue;
    const collision = model.geom_group[geom] === 3;
    const meshId = model.geom_dataid[geom];
    const name = sim.mj.mj_id2name(model, sim.mj.mjtObj.mjOBJ_MESH.value, meshId) || '';
    const color = /head_roll|trunk_base/.test(name) ? '#e7e0c8' : /ankle/.test(name) ? '#e1ad58' : /hip_pitch|knee/.test(name) ? '#78b3aa' : '#526f78';
    const material = collision
      ? new THREE.MeshBasicMaterial({color:'#edc16f', wireframe:true, transparent:true, opacity:0.32, depthWrite:false})
      : new THREE.MeshStandardMaterial({color, roughness:0.43, metalness:0.14, side:THREE.DoubleSide});
    const mesh = new THREE.Mesh(makeGeometry(meshId), material);
    mesh.matrixAutoUpdate = false;
    mesh.castShadow = !collision;
    mesh.receiveShadow = !collision;
    mesh.visible = !collision;
    const body = model.geom_bodyid[geom];
    const joint = sim.joints.find(joint => joint.index === model.body_jntadr[body]);
    mesh.userData = {geom, jointId:joint?.id};
    scene.add(mesh);
    (collision ? collisionMeshes : visualMeshes).push(mesh);
  }
  for (const joint of sim.joints) {
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(), 0.025, '#edc16f', 0.006, 0.003);
    arrow.visible = false; scene.add(arrow); jointMarkers.push({joint, arrow});
  }
}

function updateRobot() {
  const data = sim.data;
  for (const mesh of [...visualMeshes, ...collisionMeshes]) {
    const g = mesh.userData.geom, p = g * 3, m = g * 9;
    const a = data.geom_xmat, b = data.geom_xpos;
    matrix.set(a[m],a[m+1],a[m+2],b[p], a[m+3],a[m+4],a[m+5],b[p+1], a[m+6],a[m+7],a[m+8],b[p+2], 0,0,0,1);
    mesh.matrix.copy(matrix);
    if (mesh.material.emissive) mesh.material.emissive.set(mesh.userData.jointId === selected ? '#332512' : '#000000');
  }
  for (const {joint, arrow} of jointMarkers) {
    const i = joint.index * 3;
    arrow.position.fromArray(data.xanchor, i);
    arrow.setDirection(new THREE.Vector3().fromArray(data.xaxis, i));
  }
}

function updateRows() {
  const angles = mode === 'physics' && !sim.hold ? sim.angles() : sim.targetAngles();
  const freshLive = lastPacket && performance.now()-lastPacketAt<2500 && liveResult?.fresh;
  for (const joint of sim.joints) {
    const row = rows.get(joint.id);
    const missing = mode === 'live' && (!freshLive || ($('live-source').value === 'measured' && !(lastPacket?.servo_ids || []).includes(joint.id)));
    row.output.textContent = missing ? '—' : `${angles[joint.id].toFixed(1)}°`;
    row.input.value = angles[joint.id].toFixed(1);
    row.input.disabled = mode === 'live' || (mode === 'physics' && !sim.hold);
    row.element.classList.toggle('selected', selected === joint.id);
  }
}

function selectJoint(id) {
  selected = id; updateRows();
}

function buildJointControls() {
  for (const joint of sim.joints) {
    const element = document.createElement('div'); element.className = 'joint-row';
    const heading = document.createElement('div'); heading.className = 'joint-heading';
    const id = document.createElement('span'); id.className = 'motor-id'; id.textContent = joint.id;
    const button = document.createElement('button'); button.textContent = joint.label; button.addEventListener('click', () => selectJoint(joint.id));
    const output = document.createElement('output'); output.setAttribute('for', `joint-${joint.id}`);
    const input = document.createElement('input'); input.type = 'range'; input.id = `joint-${joint.id}`;
    // Align the slider's step lattice to tenths of a degree. Raw CAD limits
    // contain floating-point residues which otherwise make values like 0/35 invalid.
    input.min = Math.ceil(joint.min*10-1e-7)/10;
    input.max = Math.floor(joint.max*10+1e-7)/10;
    input.step = '0.1'; input.value = sim.targetAngles()[joint.id].toFixed(1);
    input.setAttribute('aria-label', `${joint.label} (${joint.id})`);
    input.addEventListener('input', () => {
      gait = false; selected = joint.id;
      sim.setJoint(joint.id, Number(input.value));
      sim.mj.mj_forward(sim.model, sim.data);
      $('gait').classList.remove('active'); updateModeText(); updateRows();
    });
    const range = document.createElement('div'); range.className = 'joint-range';
    for (const limit of [joint.min, joint.max]) { const label = document.createElement('span'); label.textContent = `${limit.toFixed(0)}°`; range.append(label); }
    heading.append(id, button, output); element.append(heading, input, range); $('joint-controls').append(element);
    rows.set(joint.id, {element, input, output});
  }
}

function updateModeText() {
  for (const button of document.querySelectorAll('[data-mode]')) button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
  $('physics-card').hidden = mode !== 'physics'; $('live-card').hidden = mode !== 'live';
  $('gait').classList.toggle('active', gait);
  $('play').disabled = mode === 'pose' && !gait;
  $('play').textContent = running ? (mode === 'live' ? 'Freeze view' : 'Pause') : (mode === 'live' ? 'Resume view' : 'Play');
  $('step').disabled = running || mode !== 'physics';
  $('clock-label').textContent = gait ? 'PREVIEW TIME' : 'SIM TIME';
  $('reset').textContent = mode === 'physics' ? 'Reset physics' : mode === 'live' ? 'Re-centre' : 'Reset pose';
  $('scene-mode').textContent = mode === 'physics' ? 'MUJOCO / GRAVITY + CONTACTS' : mode === 'live' ? 'LIVE / READ ONLY' : gait ? 'PROCEDURAL STEP PREVIEW' : 'POSE WORKSPACE';
  $('mode-note').textContent = mode === 'physics'
    ? 'Free-body MuJoCo physics. No balance policy is running; falling is expected. Hold targets enables the model’s approximate viewer PD.'
    : mode === 'live' ? 'Read-only telemetry. Target previews are commanded angles; missing measured joints remain unavailable.'
    : gait ? 'A procedural joint cycle for checking articulation. It is a kinematic preview, without gravity or a walking policy.'
    : 'Adjust joint angles within the CAD model’s limits. Poses are local previews; they do not send motor commands.';
  updateRows();
}

function setMode(next) {
  if (!['pose','physics','live'].includes(next)) return;
  if (next !== mode && (mode !== 'pose' || next !== 'physics')) sim.reset('STAND');
  mode = next; sim.mode = next; gait = false; gaitTime = 0; running = next !== 'pose';
  sim.data.qvel.fill(0); sim.accumulator = 0;
  if (mode === 'live' && lastPacket && performance.now()-lastPacketAt<2500) liveResult = sim.applyTelemetry(lastPacket, $('live-source').value);
  updateModeText();
}

function applyPreset(preset) {
  mode = 'pose'; sim.mode = 'pose'; running = false; gait = false; gaitTime = 0;
  sim.reset(preset); updateModeText(); $('pose-message').textContent = `${preset.toLowerCase()} pose loaded.`;
}

function animateGait(dt) {
  gaitTime += dt;
  const phase = gaitTime * Math.PI * 2 * 0.65;
  const left = Math.sin(phase), right = -left;
  sim.applyPose({10:0,11:-5,12:-22+left*11,13:Math.max(0,left)*18,14:22-left*8,
    20:0,21:5,22:22-right*11,23:-Math.max(0,right)*18,24:-22+right*8,
    30:20,31:20,32:Math.sin(phase/2)*9,33:Math.sin(phase)*4});
  sim.data.qpos[2] = 0.139158 + Math.abs(left) * 0.003;
  sim.mj.mj_forward(sim.model, sim.data);
}

function updateBoard() {
  const fresh = lastPacket && performance.now() - lastPacketAt < 2500;
  $('board-dot').style.background = fresh ? '#8edac8' : '#edc16f';
  $('board-state').textContent = fresh ? 'Connected' : 'Not connected';
  $('board-feedback').textContent = fresh ? `${lastPacket.feedback_hz.toFixed(1)} Hz` : '—';
  $('board-servos').textContent = fresh ? `${lastPacket.servo_ids?.length || 0}/15` : '—';
  $('board-gpu').textContent = fresh && lastPacket.gpu?.available ? `${lastPacket.gpu.load_percent.toFixed(1)}%` : '—';
  $('board-torque').textContent = fresh && typeof lastPacket.enabled === 'boolean' ? (lastPacket.enabled ? 'Hardware torque ON' : 'Hardware torque off') : 'Torque status unknown';
  $('board-torque').classList.toggle('warning', fresh && lastPacket.enabled === true);
  if (mode === 'live') {
    const type = $('live-source').value === 'targets' ? 'Commanded targets' : 'Measured joints';
    $('live-health').textContent = !fresh ? 'Connection lost. The last pose is frozen.'
      : !liveResult?.fresh ? 'MCU feedback is stale. The last pose is frozen.'
      : `${type}: ${liveResult.used}/14 available. Measured motors: ${liveResult.measured}/14. IMU ${liveResult.imu ? 'online (roll/pitch)' : 'offline'}.${running ? '' : ' View frozen.'}`;
    for (const mesh of visualMeshes) {
      const ghost = $('live-source').value === 'targets' || !fresh || !liveResult?.fresh || liveResult.used<14;
      if (mesh.material.transparent !== ghost) mesh.material.needsUpdate = true;
      mesh.material.transparent = ghost;
      mesh.material.opacity = ghost ? 0.55 : 1;
    }
  } else for (const mesh of visualMeshes) {
    if (mesh.material.transparent) mesh.material.needsUpdate = true;
    mesh.material.transparent = false; mesh.material.opacity = 1;
  }
}

async function pollBoard() {
  if (stopping) return;
  if (!document.hidden) {
    try {
      const response = await fetch('/api/status', {cache:'no-store', signal:AbortSignal.timeout(1800)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const packet = await response.json();
      if (typeof packet.feedback_hz !== 'number') throw new Error('Invalid telemetry');
      lastPacket = packet; lastPacketAt = performance.now();
      if (sim && mode === 'live' && running) liveResult = sim.applyTelemetry(packet, $('live-source').value);
    } catch { /* The age check replaces stale readings with unavailable indicators. */ }
  }
  updateBoard();
  setTimeout(pollBoard, mode === 'live' && !document.hidden ? 200 : 1000);
}

function attachControls() {
  document.querySelectorAll('[data-mode]').forEach(button => { button.disabled=false; button.addEventListener('click', () => setMode(button.dataset.mode)); });
  document.querySelectorAll('[data-preset]').forEach(button => { button.disabled = false; button.addEventListener('click', () => applyPreset(button.dataset.preset)); });
  for (const id of ['reset','camera','gait','export','import']) $(id).disabled = false;
  $('reset').addEventListener('click', () => {
    sim.reset('STAND'); gaitTime = 0;
    if (mode === 'pose') { gait=false; running=false; }
    updateModeText();
  });
  $('camera').addEventListener('click', resetCamera);
  $('play').addEventListener('click', () => { running = !running; sim.accumulator = 0; updateModeText(); });
  $('gait').addEventListener('click', () => {
    if (gait) { gait = false; running = false; } else { setMode('pose'); sim.reset('STAND'); gait = true; running = true; }
    updateModeText();
  });
  $('drop').addEventListener('click', () => { sim.drop(); mode = 'physics'; running = true; updateModeText(); });
  $('nudge').addEventListener('click', () => sim.nudge());
  $('step').addEventListener('click', () => { if (!running && mode === 'physics') sim.step(10); });
  $('hold').addEventListener('change', () => { sim.setHold($('hold').checked); updateRows(); });
  $('gravity').addEventListener('input', () => { sim.setGravity(Number($('gravity').value)); $('gravity-value').textContent = `${Number($('gravity').value).toFixed(2)} m/s²`; });
  $('friction').addEventListener('input', () => { sim.setFriction(Number($('friction').value)); $('friction-value').textContent = Number($('friction').value).toFixed(2); });
  $('collisions').addEventListener('change', () => collisionMeshes.forEach(mesh => { mesh.visible = $('collisions').checked; }));
  $('axes').addEventListener('change', () => jointMarkers.forEach(({arrow}) => { arrow.visible = $('axes').checked; }));
  $('live-source').addEventListener('change', () => { if (lastPacket && performance.now()-lastPacketAt<2500) liveResult = sim.applyTelemetry(lastPacket, $('live-source').value); updateRows(); updateBoard(); });
  $('export').addEventListener('click', () => {
    const pose = {schema:1, robot:'xgoduck', joints_deg:sim.targetAngles()};
    const url = URL.createObjectURL(new Blob([JSON.stringify(pose,null,2)+'\n'], {type:'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'xgoduck-pose.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); $('pose-message').textContent = 'Pose saved locally. No motor commands sent.';
  });
  $('import').addEventListener('click', () => $('pose-file').click());
  $('pose-file').addEventListener('change', async () => {
    const file = $('pose-file').files[0];
    if (!file) return;
    try {
      if (file.size > 65536) throw new Error('Pose files must be smaller than 64 KB.');
      const angles = parsePose(JSON.parse(await file.text()), sim.joints);
      setMode('pose'); sim.applyPose(angles); updateRows();
      $('pose-message').textContent = 'Pose loaded locally. No motor commands sent.';
    } catch (error) { $('pose-message').textContent = error.message; }
    $('pose-file').value = '';
  });
  viewport.addEventListener('keydown', event => {
    if (event.code === 'Space' && !$('play').disabled) { event.preventDefault(); $('play').click(); }
  });
  let down = null;
  renderer.domElement.addEventListener('pointerdown', event => { down = {x:event.clientX,y:event.clientY}; });
  renderer.domElement.addEventListener('pointerup', event => {
    if (!down || Math.hypot(down.x-event.clientX,down.y-event.clientY)>5) return;
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX-rect.left)/rect.width*2-1, -(event.clientY-rect.top)/rect.height*2+1);
    raycaster.setFromCamera(pointer,camera);
    const hit = raycaster.intersectObjects(visualMeshes).find(hit => hit.object.userData.jointId);
    if (hit) selectJoint(hit.object.userData.jointId);
  });
}

function frame(time) {
  if (document.hidden) { previousFrame = 0; sim.accumulator = 0; return; }
  const dt = previousFrame ? Math.min((time-previousFrame)/1000,0.05) : 0;
  previousFrame = time;
  try {
    if (running && mode === 'physics') sim.advance(dt*Number($('speed').value));
    if (running && mode === 'pose' && gait) animateGait(dt);
    updateRobot(); orbit.update(); renderer.render(scene,camera);
    fpsFrames++;
    if (time-fpsStart>600) { fps=fpsFrames*1000/(time-fpsStart); fpsFrames=0; fpsStart=time; }
    if (time-lastHud>200) {
      $('fps').textContent = Math.round(fps); $('sim-time').textContent = (gait ? gaitTime : sim.data.time).toFixed(2);
      $('contacts').textContent = mode === 'physics' ? sim.data.ncon : '—';
      $('height').textContent = (sim.data.qpos[2]*100).toFixed(1);
      updateRows(); updateBoard(); lastHud=time;
    }
  } catch (error) { running=false; updateModeText(); showError(error); }
}

async function start() {
  scene = new THREE.Scene(); scene.background = new THREE.Color('#0c1720');
  camera = new THREE.PerspectiveCamera(36,1,0.005,12); camera.up.set(0,0,1);
  renderer = new THREE.WebGPURenderer({antialias:true, alpha:false});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1,1.5));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  await renderer.init();
  const webgpu = Boolean(renderer.backend.isWebGPUBackend);
  $('renderer-state').textContent = webgpu ? 'WEBGPU · CLIENT GPU' : 'WEBGL 2 · FALLBACK';
  $('engine-note').textContent = webgpu ? 'WebGPU graphics on this viewing device · MuJoCo physics on its CPU · UNO Q serves the app.'
    : `${window.isSecureContext ? 'This browser selected WebGL 2.' : 'Wi-Fi HTTP uses WebGL 2; open localhost over USB for WebGPU.'} Physics runs on this viewing device’s CPU.`;
  viewport.prepend(renderer.domElement);
  orbit = new OrbitControls(camera,renderer.domElement); orbit.enableDamping=true;
  orbit.minDistance=0.15; orbit.maxDistance=1.8; orbit.maxPolarAngle=Math.PI*0.49; resetCamera();
  scene.add(new THREE.HemisphereLight('#e8f9ff','#294443',2.6));
  const light = new THREE.DirectionalLight('#fff3db',3.2); light.position.set(-0.3,-0.4,0.8); scene.add(light);
  const fill = new THREE.DirectionalLight('#8edac8',1.8); fill.position.set(0.5,0.25,0.4); scene.add(fill);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(4,4),new THREE.MeshStandardMaterial({color:'#15252c',roughness:0.95}));
  ground.position.z=-0.0005; scene.add(ground);
  const grid = new THREE.GridHelper(2,40,'#47606b','#243b46'); grid.rotation.x=Math.PI/2; grid.position.z=0.0001; scene.add(grid);
  const axes = new THREE.AxesHelper(0.05); axes.position.set(-0.16,-0.13,0.001); scene.add(axes);
  const resize = new ResizeObserver(() => {
    const width = viewport.clientWidth, height = viewport.clientHeight;
    camera.aspect=width/height; camera.updateProjectionMatrix(); renderer.setSize(width,height,false);
  }); resize.observe(viewport);
  sim = await DuckSimulation.create();
  buildRobot(); buildJointControls(); attachControls(); updateModeText(); updateRobot();
  await renderer.compileAsync(scene,camera);
  $('loading').hidden=true;
  renderer.setAnimationLoop(frame);
  pollBoard();
  window.addEventListener('pagehide',event => {
    if (event.persisted) return;
    stopping=true; resize.disconnect(); renderer.setAnimationLoop(null); orbit.dispose();
    for (const mesh of [...visualMeshes,...collisionMeshes]) mesh.material.dispose();
    for (const geometry of geometryCache.values()) geometry.dispose();
    sim.dispose(); renderer.dispose();
  },{once:true});
}

start().catch(error => {
  $('loading').textContent = 'The 3D workspace could not start.';
  showError(error);
});
