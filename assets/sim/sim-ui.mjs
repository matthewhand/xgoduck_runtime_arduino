import * as THREE from 'three';
import {OrbitControls} from './vendor/three/OrbitControls.js';
import {DuckSimulation, parsePose} from './sim-core.mjs?v=4';
import {WalkPanel} from './walk-ui.mjs?v=7';
import {DemoCircuit} from './demo-ui.mjs?v=3';
import {QualificationReplay, SKATE_TURN_LOOP, loadDockCase, usesSkates} from './qualification-replay.mjs?v=21';
import {GuardPreview} from './guard-preview.mjs?v=10';
import {DOCK_DESIGNS, dockSurfaceGeometry} from './dock-preview.mjs?v=7';
import {SKATE_SURFACES} from './skate-terrain.mjs';
import {mountMatrixControls} from './matrix-ui.mjs?v=2';

import {modPolicyStatus} from './mod-policy.mjs?v=4';
import {loadModPreview, showModLayers} from './mod-preview.mjs?v=2';

const $ = id => document.getElementById(id);
const query = new URLSearchParams(location.search);
const stockView = query.get('stock') === '1';
const viewport = $('viewport');
const layout = $('sim-layout');
const controls = $('sim-controls');
const fullscreenButton = $('sim-fullscreen');
const compactLayout = matchMedia('(max-width: 600px), (max-width: 960px) and (max-height: 500px)');
const updateControlsLayout = () => {
  if (!layout.classList.contains('is-fullscreen')) controls.open = !compactLayout.matches;
};
compactLayout.addEventListener('change', updateControlsLayout);
updateControlsLayout();

let controlsBeforeFullscreen, compactBeforeFullscreen;
let fullscreenPending = false;
function setFullscreenLayout(active) {
  if (layout.classList.contains('is-fullscreen') === active) return;
  if (active) {
    controlsBeforeFullscreen = controls.open;
    compactBeforeFullscreen = compactLayout.matches;
  }
  layout.classList.toggle('is-fullscreen', active);
  document.documentElement.classList.toggle('sim-fullscreen', active);
  controls.open = !active && (compactLayout.matches === compactBeforeFullscreen ? controlsBeforeFullscreen : !compactLayout.matches);
  fullscreenButton.textContent = active ? 'Exit fullscreen' : 'Fullscreen';
  fullscreenButton.focus({preventScroll: true});
}

fullscreenButton.addEventListener('click', async () => {
  if (fullscreenPending) return;
  if (layout.classList.contains('is-fullscreen')) {
    if (document.fullscreenElement === layout) await document.exitFullscreen();
    else setFullscreenLayout(false);
    return;
  }
  setFullscreenLayout(true);
  if (!document.fullscreenEnabled || !layout.requestFullscreen) return;
  fullscreenPending = true;
  try { await layout.requestFullscreen(); }
  catch { /* Keep the viewport-filling layout when native fullscreen is blocked. */ }
  finally { fullscreenPending = false; }
});
document.addEventListener('fullscreenchange', () => {
  if (document.fullscreenElement !== layout) setFullscreenLayout(false);
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !fullscreenPending && !document.fullscreenElement && layout.classList.contains('is-fullscreen')) {
    event.preventDefault();
    setFullscreenLayout(false);
  }
});
fullscreenButton.hidden = false;

const walk = new WalkPanel();
const demo = new DemoCircuit(walk, showDemoScene, updateDemoStatus);
const rolloutMode = name => name === 'walk' || name === 'explore';
const playground = name => name === 'physics' || name === 'skates';
let sim, renderer, orbit, camera, scene;
let stockSim, skateSim, skateLoad, workspaceRequest = 0, wheelsExploded = false;
let mode = 'pose', running = false, gait = false, gaitTime = 0, selected = 32;
let demoMode = false;
let lastPacket = null, lastPacketAt = 0, liveResult = null, stopping = false;
let previousFrame = 0, fpsStart = 0, fpsFrames = 0, fps = 0, lastHud = 0;
const geometryCache = new Map(), visualMeshes = [], collisionMeshes = [], jointMarkers = [];
const rows = new Map();
const matrix = new THREE.Matrix4();
const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
const walkRotation = new THREE.Quaternion(), walkTarget = new THREE.Quaternion();
let walkRun = null;
let searchWorld, searchBeacon, searchWaypoint, wallGeometry, wallMaterial;
let terrain, towLine, towPoint, skateTrack;
let floorGroup, ground, grid, shownSkateTerrain, visibleSprintTiles;
const sprintTiles = new Map();
let replay, lastReplayPose, replayModules = [];
let dockOverhead = false;
let modPreview, modLoad, dino, dinoModule, dinoLoad, skinModule;
let tailPreview, tailLoad, tailGeneration = 0, tailClock = 0, tailPlaying = false;
let modRequest = 0, jawBody = -1, appliedSkin = 'plain', appliedJawSkin = 'plain';
let guardPreview, hardwareAssembly = 'translucent';
const assemblyCamera = assembly => assembly === 'dock' ? 'dock' : assembly === 'exploded' ? 'side' : 'rear';

function sprintGroundHeight(config, x, y) {
  if (!config) return 0;
  const radians = THREE.MathUtils.degToRad;
  return x * Math.tan(radians(config.grade_deg ?? 0)) + y * Math.tan(radians(config.cross_deg ?? 0));
}

function showError(error) {
  $('error').hidden = false;
  $('error').textContent = error.message || String(error);
}

function resetCamera() {
  orbit.maxDistance = mode === 'explore' ? 4.5 : 1.8;
  orbit.minDistance = mode === 'hardware' || mode === 'mods' ? .075 : .15;
  if (mode === 'mods') {
    if (($('mod-teeth').checked || $('mod-tusks').checked) && jawBody >= 0) setJawCamera();
    else if ($('mod-tail').checked) setTailCamera();
    else setHardwareCamera($('mod-skin').value !== 'plain' && !$('mod-pack').checked ? 'side' : 'rear');
    return;
  }
  if (mode === 'hardware') {
    setHardwareCamera(assemblyCamera(hardwareAssembly));
    return;
  }
  if (mode === 'explore') {
    camera.position.set(1.85, -2.25, 2.25);
    orbit.target.set(.78, 0, .04);
    orbit.update();
    return;
  }
  const follow = mode === 'walk' || mode === 'replay';
  const x = follow ? sim.data.qpos[0] : 0;
  const y = follow ? sim.data.qpos[1] : 0;
  if (mode === 'replay' && replay.trial?.result.dock) {
    const approach = typeof replay.trial.result.dock.approach_reached === 'boolean';
    if (approach) {
      if (replay.trial.result.dock.navigation) {
        const points = replay.trial.result.trace.map(frame => frame.root);
        const xs = [0, ...points.map(p => p[0])], ys = [0, ...points.map(p => p[1])];
        const cx = (Math.min(...xs) + Math.max(...xs))/2, cy = (Math.min(...ys) + Math.max(...ys))/2;
        const rx = Math.max(...xs) - cx + .13, ry = Math.max(...ys) - cy + .15;
        const t = Math.tan(THREE.MathUtils.degToRad(camera.fov/2));
        const range = Math.max(.65, rx/(t*camera.aspect), ry/t);
        orbit.maxDistance = Math.max(1.8, range*2);
        camera.position.set(cx, cy-(dockOverhead ? .002 : range*.8), .08+range*(dockOverhead ? 1 : .8));
        orbit.target.set(cx, cy, .08);
      } else if (replay.trial.result.dock.qualification || replay.trial.result.dock.lowering_test || replay.trial.result.dock.bar_entry) {
        // Frame the chair and the farthest roll-away from either clip.
        let far = 0;
        for (const {result} of replay.trials.values()) for (const frame of result.trace) {
          far = Math.max(far, frame.root[0]);
        }
        const near = -.08;
        far += .16;
        const centre = (near + far) / 2;
        const distance = Math.max(.75, (far - near) * .58 /
          (Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect));
        camera.position.set(centre + (dockOverhead ? 0 : .14), dockOverhead ? -.002 : -distance,
          dockOverhead ? Math.max(.88, distance) : .36);
        orbit.target.set(centre, 0, .08);
      } else {
        const centre = replay.trial.result.trace[0].root[0] / 2;
        camera.position.set(centre + (dockOverhead ? 0 : .2), dockOverhead ? -.002 : -.63, dockOverhead ? .82 : .38);
        orbit.target.set(centre, 0, .05);
      }
    } else if (dockOverhead) {
      camera.position.set(x, y-.002, .64);
      orbit.target.set(x, y, .055);
    } else {
      const floorHeight = sprintGroundHeight(replay.trial?.result.skate?.terrain, x, y);
      camera.position.set(x+.27, y-.36, .26+floorHeight);
      orbit.target.set(x+.025, y, .10+floorHeight);
    }
  } else {
    camera.position.set(x+0.36, y-0.43, 0.28);
    orbit.target.set(x+0.012, y, 0.145);
  }
  orbit.update();
}

function setHardwareCamera(view = 'rear') {
  if (view === 'matrix') {
    camera.position.set(-.198,.014326,.10888);
    orbit.target.set(-.074,.014326,.10888);
  } else if (view === 'dock') {
    camera.position.set(-.39,-.385,.283);
    orbit.target.set(-.082,0,.114);
  } else {
    camera.position.set(...(view === 'side' ? [-.271,-.440,.246] : [-.466,-.025,.191]));
    orbit.target.set(-.042,0,.133);
  }
  orbit.update();
}

function setTailCamera() {
  const [x, y, h] = sim.data.qpos;
  orbit.target.set(x - .07, y, h - .025);
  camera.position.copy(orbit.target).add(new THREE.Vector3(-.14, -.45, .12));
  orbit.update();
}

function setJawCamera() {
  orbit.target.fromArray(sim.data.xpos, jawBody * 3);
  camera.position.copy(orbit.target).add(new THREE.Vector3(.16, -.23, .08));
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
  jawBody = sim.mj.mj_name2id(model, sim.mj.mjtObj.mjOBJ_BODY.value, 'jaw_soft');
  for (let geom = 0; geom < model.ngeom; geom++) {
    if (model.geom_type[geom] !== sim.mj.mjtGeom.mjGEOM_MESH.value) continue;
    const collision = model.geom_group[geom] === 3;
    const meshId = model.geom_dataid[geom];
    const name = sim.mj.mj_id2name(model, sim.mj.mjtObj.mjOBJ_MESH.value, meshId) || '';
    const wheel = /^(left|right)_(front|rear)_tire$/.exec(name);
    const color = wheel ? '#344959' : /head_roll|trunk_base/.test(name) ? '#e7e0c8' : /ankle/.test(name) ? '#e1ad58' : /hip_pitch|knee/.test(name) ? '#78b3aa' : '#526f78';
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
    mesh.userData = {geom, meshName: name, jointId:joint?.id, wheelSide:wheel?.[1], bodyJoint:model.body_jntadr[body]};
    scene.add(mesh);
    (collision ? collisionMeshes : visualMeshes).push(mesh);
  }
  for (const joint of sim.joints) {
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(), 0.025, '#edc16f', 0.006, 0.003);
    arrow.visible = false; scene.add(arrow); jointMarkers.push({joint, arrow});
  }
}

function clearRobot() {
  if (appliedSkin !== 'plain') skinModule?.setShellSkin(visualMeshes, sim, 'plain');
  appliedSkin = 'plain';
  for (const mesh of [...visualMeshes, ...collisionMeshes]) {
    scene.remove(mesh);
    mesh.material.dispose();
  }
  for (const {arrow} of jointMarkers) {
    scene.remove(arrow);
    arrow.line.material.dispose();
    arrow.cone.material.dispose();
  }
  for (const geometry of geometryCache.values()) geometry.dispose();
  visualMeshes.length = collisionMeshes.length = jointMarkers.length = 0;
  geometryCache.clear();
}

function buildSkateScene() {
  terrain = {};
  for (const [surface, boxes] of Object.entries(SKATE_SURFACES)) {
    const group = terrain[surface] = new THREE.Group();
    group.visible = false;
    scene.add(group);
    for (const {size, center} of boxes) {
      const color = surface.startsWith('tiles') ? '#92998e' : '#de9c60';
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), new THREE.MeshStandardMaterial({color}));
      mesh.position.set(...center);
      group.add(mesh);
    }
  }
  const carpet = new THREE.Mesh(new THREE.PlaneGeometry(2.8,1.6),
    new THREE.MeshStandardMaterial({color:'#524760',roughness:1}));
  carpet.position.z = .0002;
  terrain.carpet.add(carpet);
  towLine = new THREE.Line(new THREE.BufferGeometry().setAttribute('position',
    new THREE.Float32BufferAttribute(new Float32Array(6),3)), new THREE.LineBasicMaterial({color:'#edc16f'}));
  towLine.frustumCulled = false;
  towLine.visible = false;
  towPoint = new THREE.Mesh(new THREE.SphereGeometry(.008,12,8), new THREE.MeshBasicMaterial({color:'#edc16f'}));
  towPoint.visible = false;
  const laneMarks = [];
  for (let x = 0; x <= 8; x += .25) laneMarks.push(x, -.15, .001, x, .15, .001);
  skateTrack = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',
    new THREE.Float32BufferAttribute(laneMarks, 3)), new THREE.LineBasicMaterial({color:'#7caeaa'}));
  skateTrack.visible = false;
  scene.add(towLine,towPoint,skateTrack);
}

function sprintTileMesh(config) {
  const {tile_m: spacing, grout_depth_m: depth, gap_m: gap, tile_columns: columns, tile_origin_m: origin} = config;
  if (![.45, .60].includes(spacing) || !Array.isArray(columns) || columns.length > 32
      || !columns.every(Number.isInteger) || ![depth, gap, origin].every(Number.isFinite)
      || depth <= 0 || gap <= 0 || gap >= spacing) throw new Error('Invalid tile replay geometry.');
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(spacing-gap, spacing-gap, depth),
    new THREE.MeshStandardMaterial({roughness:.94}), 3*columns.length);
  const colors = [new THREE.Color('#576f74'), new THREE.Color('#4c6268')];
  let index = 0;
  for (const row of [-1,0,1]) for (const col of columns) {
    matrix.makeTranslation(origin+(col+.5)*spacing, row*spacing, -depth/2);
    mesh.setMatrixAt(index, matrix);
    mesh.setColorAt(index++, colors[Math.abs(row+col)%2]);
  }
  scene.add(mesh);
  return mesh;
}

function showSprintTerrain(config) {
  if (config === shownSkateTerrain) return;
  shownSkateTerrain = config;
  if (visibleSprintTiles) visibleSprintTiles.visible = false;
  if (config?.tile_m) {
    if (!sprintTiles.has(config.label)) sprintTiles.set(config.label, sprintTileMesh(config));
    visibleSprintTiles = sprintTiles.get(config.label);
    visibleSprintTiles.visible = true;
  }
  const radians = THREE.MathUtils.degToRad;
  floorGroup.rotation.set(radians(config?.cross_deg ?? 0), -radians(config?.grade_deg ?? 0), 0);
  floorGroup.position.z = -(config?.grout_depth_m ?? 0);
  skateTrack.rotation.copy(floorGroup.rotation);
  ground.material.color.set(config?.axle_damping ? '#4b405b' : '#15252c');
  grid.visible = !config?.axle_damping;
}

function updateSkateScene() {
  const recording = mode === 'replay' && replay.trial?.result.skate;
  skateTrack.visible = Boolean(recording);
  showSprintTerrain(recording?.terrain);
  for (const [name, group] of Object.entries(terrain)) group.visible = mode === 'skates' && sim.surface === name;
  const tow = mode === 'skates' && sim.tow;
  towPoint.visible = towLine.visible = Boolean(tow && !wheelsExploded && tow.status === 'Pulling');
  if (towLine.visible) {
    tow.samplePoint();
    const line = towLine.geometry.attributes.position;
    line.setXYZ(0,...tow.point);
    line.setXYZ(1,...tow.target);
    line.needsUpdate = true;
    towPoint.position.fromArray(tow.target);
  }
}

function updateRobot() {
  const data = sim.data;
  for (const mesh of [...visualMeshes, ...collisionMeshes]) {
    const g = mesh.userData.geom, p = g * 3, m = g * 9;
    const a = data.geom_xmat, b = data.geom_xpos;
    matrix.set(a[m],a[m+1],a[m+2],b[p], a[m+3],a[m+4],a[m+5],b[p+1], a[m+6],a[m+7],a[m+8],b[p+2], 0,0,0,1);
    const {wheelSide, bodyJoint} = mesh.userData;
    if (wheelsExploded && wheelSide) {
      const axle = bodyJoint * 3;
      const direction = (data.xaxis[axle+1] < 0 ? -1 : 1) * (wheelSide === 'left' ? .028 : -.028);
      for (let i = 0; i < 3; i++) matrix.elements[12+i] += data.xaxis[axle+i] * direction;
    }
    mesh.matrix.copy(matrix);
    mesh.matrixWorldNeedsUpdate = true;
    if (mesh.material.emissive) mesh.material.emissive.set(mesh.userData.jointId === selected ? '#332512' : '#000000');
  }
  for (const {joint, arrow} of jointMarkers) {
    const i = joint.index * 3;
    arrow.position.fromArray(data.xanchor, i);
    arrow.setDirection(new THREE.Vector3().fromArray(data.xaxis, i));
  }
}

function updateRows() {
  const angles = rolloutMode(mode) || (playground(mode) && !sim.hold) ? sim.angles() : sim.targetAngles();
  const freshLive = lastPacket && performance.now()-lastPacketAt<2500 && liveResult?.fresh;
  for (const joint of sim.joints) {
    const row = rows.get(joint.id);
    const missing = mode === 'live' && (!freshLive || ($('live-source').value === 'measured' && !(lastPacket?.servo_ids || []).includes(joint.id)));
    row.output.textContent = missing ? '—' : `${angles[joint.id].toFixed(1)}°`;
    row.input.value = angles[joint.id].toFixed(1);
    row.input.disabled = rolloutMode(mode) || mode === 'live' || (playground(mode) && (!sim.hold || wheelsExploded));
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
  const rollout = rolloutMode(mode);
  const replaying = mode === 'replay';
  const dockingReplay = replaying && Boolean(replay.trial?.result.dock);
  const skateReplay = replaying && replay.trial?.result.skate;
  const skateTerrain = skateReplay?.terrain;
  const inspecting = mode === 'hardware' || mode === 'mods';
  const hardware = mode === 'hardware';
  $('mods-card').hidden = mode !== 'mods';
  const skates = mode === 'skates';
  const physics = mode === 'walk' || mode === 'physics';
  const tab = demoMode ? 'demo' : physics ? 'walk' : mode;
  for (const button of document.querySelectorAll('[data-mode]')) button.setAttribute('aria-pressed', String(button.dataset.mode === tab));
  $('physics-controller-label').hidden = !physics || demoMode;
  if (physics) $('physics-controller').value = mode;
  $('demo-card').hidden = !demoMode;
  $('joint-card').hidden = demoMode || replaying || inspecting;
  $('qualification-card').hidden = !replaying;
  $('hardware-card').hidden = $('hardware-views').hidden = $('hardware-toolbar').hidden = !hardware;
  $('sim-toolbar').hidden = $('sim-stats').hidden = inspecting;
  $('matrix-player').hidden = $('board-strip').hidden = inspecting || skates || dockingReplay || Boolean(skateReplay);
  $('qualification-title').textContent = skateTerrain ? 'Terrain speed trials' : skateReplay ? 'Skate speed trials' : stockView ? 'Stock simulation replay' : dockingReplay ? 'Docking replay' : 'Qualification replay';
  $('qualification-case-field').querySelector('label').textContent = skateTerrain ? 'Surface' : stockView ? 'Trial' : 'Entry';
  $('qualification-variant-field').hidden = Boolean(skateTerrain);
  $('qualification-variant-field').querySelector('label').textContent = skateReplay ? 'Run' : 'Design';
  $('skate-speed-data').hidden = $('skate-hud').hidden = !skateReplay;
  if (skateReplay) {
    $('skate-run-label').textContent = skateTerrain?.label ?? skateReplay.profile;
    $('skate-speed-data').href = `sim/${skateTerrain ? 'skate-terrain' : 'skate-speed'}-recording.json`;
  }
  const dockSelectors = $('dock-replay-selectors');
  const selectorsDestination = dockingReplay ? dockSelectors : $('qualification-selectors');
  for (const id of ['qualification-case-field', 'qualification-variant-field', 'qualification-alternate-label']) {
    const field = $(id);
    if (field.parentElement !== selectorsDestination) selectorsDestination.append(field);
  }
  dockSelectors.hidden = !dockingReplay;
  $('dock-overhead').hidden = !dockingReplay;
  $('dock-overhead').setAttribute('aria-pressed', String(dockOverhead));
  if (!dockingReplay) $('dock-contact-overlay').hidden = true;
  $('mode-note').hidden = inspecting;
  $('physics-card').hidden = !playground(mode) || demoMode;
  $('physics-title').textContent = skates ? 'Roller skates' : 'Physics playground';
  $('skate-tools').hidden = !skates || demoMode;
  $('skate-settings').hidden = !skates;
  $('joint-count').textContent = skates ? '14 SERVOS' : '14 DOF';
  $('explode-wheels').setAttribute('aria-pressed', String(wheelsExploded));
  $('explode-wheels').textContent = wheelsExploded ? 'Assemble wheels' : 'Explode wheels';
  $('live-card').hidden = mode !== 'live';
  $('live-source').disabled = demoMode;
  $('walk-card').hidden = $('walk-hud').hidden = !rollout; $('pose-card').hidden = rollout || demoMode || replaying || inspecting || skates;
  $('play').hidden = $('reset').hidden = rollout || demoMode;
  $('collisions').parentElement.hidden = rollout;
  $('export').disabled = rollout;
  collisionMeshes.forEach(mesh => { mesh.visible = !rollout && !inspecting && $('collisions').checked; });
  jointMarkers.forEach(({arrow}) => { arrow.visible = !inspecting && $('axes').checked; });
  $('gait').classList.toggle('active', gait);
  $('play').disabled = (mode === 'pose' && !gait) || (replaying && (!replay.frame || replay.duration === 0));
  $('reset').disabled = replaying && !replay.frame;
  $('play').textContent = running ? (mode === 'live' ? 'Freeze view' : 'Pause') : (mode === 'live' ? 'Resume view' : 'Play');
  $('step').disabled = running || !playground(mode) || wheelsExploded;
  $('nudge').disabled = wheelsExploded;
  $('clock-label').textContent = replaying ? 'REPLAY TIME' : gait ? 'PREVIEW TIME' : 'SIM TIME';
  $('reset').textContent = replaying ? 'Rewind' : playground(mode) ? 'Reset physics' : mode === 'live' ? 'Re-centre' : 'Reset pose';
  $('scene-mode').parentElement.hidden = inspecting;
  const recordedDock = replay?.trial?.result.dock;
  const outcome = recordedDock?.bar_entry?.dock_and_exit ? 'Exited forward'
    : recordedDock?.pads_loaded ? 'Pads loaded, exit missed' : 'Missed pads';
  const dockSceneLabel = recordedDock?.navigation ? navigationLabel(replay.frame, recordedDock.navigation)
    : recordedDock?.qualification ? `${replay.selectedLabel} · #${recordedDock.qualification.id}`
    : recordedDock?.bar_entry ? `${replay.selectedLabel} · ${outcome}`
    : recordedDock?.lowering_test ? replay.selectedLabel : recordedDock?.chair ? 'CHAIR DOCK' : 'FLOOR DOCK';
  $('scene-mode').textContent = skateTerrain ? 'TERRAIN SPEED TRIAL' : skateReplay ? 'SKATE SPEED TRIAL' : skates ? 'PHYSICS / ROLLER SKATES' : dockingReplay ? dockSceneLabel : replaying ? (stockView ? 'STOCK SIMULATION' : 'QUALIFICATION REPLAY') : mode === 'explore' ? 'EXPLORE / BEACON HUNT' : mode === 'walk' ? 'PHYSICS / WALKING POLICY' : mode === 'physics' ? 'PHYSICS / PLAYGROUND' : mode === 'live' ? 'LIVE / READ ONLY' : gait ? 'PROCEDURAL STEP PREVIEW' : 'POSE WORKSPACE';
  $('mode-note').textContent = mode === 'physics'
    ? 'Try a drop, a nudge, or lower gravity. Select Walking policy to let the trained controller balance the Duck.'
    : skates ? 'Replay the fastest roller-policy run or try a passive roll on the selected surface.'
    : skateTerrain ? 'Each clip shows the fastest clean setting for that surface. Choose a surface or cycle through all of them.'
    : skateReplay ? 'Recorded MuJoCo trial. Compare the shipped roller policy from rest with the previous passive push.'
    : mode === 'explore' ? 'Watch the Duck build a range map and choose its next destination. The beacon appears when its scan reaches it.'
    : mode === 'walk' ? 'The UNO Q runs the shipped walking ONNX policy and MuJoCo on its CPU. This view follows the simulated Duck. No motor commands are sent.'
    : mode === 'live' ? 'Read-only telemetry. Target previews are commanded angles; missing measured joints remain unavailable.'
    : dockingReplay && recordedDock.navigation ? `${recordedDock.navigation.outcome} · Teal shows the recorded path. Steering uses the simulated dock pose.`
    : dockingReplay && recordedDock.qualification ? `${recordedDock.qualification.outcome} · ${recordedDock.qualification.cohort_clean}/100 clean exits on ${recordedDock.skates ? 'skates' : 'feet'}.`
    : dockingReplay && replay.trial.result.dock.bar_entry ? 'Orange marks the trip bar. Loaded contacts turn gold.'
    : dockingReplay ? (replay.trial.result.dock.contact_force_n
      ? 'The chair supports the Duck on two fixed pads. The force readouts show mechanical loading. The blue line marks where lowering starts.'
      : replay.trial.result.dock.chair
      ? (typeof replay.trial.result.dock.approach_reached === 'boolean'
        ? 'This trial starts outside the chair. The feet walk backwards and the skates start in a backward coast. Gold marks contact.'
        : 'This trial starts just clear of the backrest. The Duck settles with torque off before rising. Gold marks contact.')
      : 'The Duck settles with torque off. The shipped controller takes over after 1.2 s. Gold marks contact.')
    : replaying ? (stockView ? 'Recorded stock MuJoCo trials. Use Trial to choose walking or a get-up.' : 'Recorded MuJoCo poses. Switch variants to compare at the same time. Gold accessory shapes mark contact.')
    : gait ? 'A procedural joint cycle for checking articulation. It is a kinematic preview, without gravity or a walking policy.'
    : 'Adjust joint angles within the CAD model’s limits. Poses are local previews; they do not send motor commands.';
  updateRows();
}

function setMode(next) {
  if (!['pose','physics','walk','explore','live','replay','hardware','mods','skates'].includes(next)) return;
  if (next === 'hardware' && !guardPreview) {
    guardPreview = new GuardPreview();
    scene.add(guardPreview.group);
  }
  const previousMode = mode;
  if (previousMode === 'mods' && next !== 'mods') {
    ++modRequest;
    ++tailGeneration;
    tailPlaying = false;
    if (dino) dino.visible = false;
    if (appliedSkin !== 'plain') skinModule?.setShellSkin(visualMeshes, sim, 'plain');
    appliedSkin = 'plain';
    for (const mesh of visualMeshes) mesh.visible = true;
  }
  const changedWalk = mode !== next && (rolloutMode(mode) || rolloutMode(next));
  const changedReplay = mode !== next && (mode === 'replay' || next === 'replay');
  const changedHardware = mode !== next && (mode === 'hardware' || next === 'hardware');
  const changedSkates = mode !== next && (mode === 'skates' || next === 'skates');
  if (next !== mode && (mode !== 'pose' || next !== 'physics')) sim.reset('STAND');
  mode = next; sim.mode = playground(next) ? 'physics' : next;
  wheelsExploded = false; gait = false; gaitTime = 0; running = next === 'physics' || next === 'live';
  walk.setMode(mode, demoMode);
  if (changedWalk) searchWorld.visible = false;
  if (changedWalk) { walkRun = null; resetCamera(); }
  if (changedReplay) {
    lastReplayPose = null;
    updateReplayModules(mode === 'replay' ? replay.trial?.modules : []);
    if (mode === 'replay') applyReplayPose();
    resetCamera();
  }
  if (guardPreview) guardPreview.group.visible = mode === 'hardware';
  if (modPreview) modPreview.visible = mode === 'mods';
  if (changedHardware || changedSkates || next === 'mods' || previousMode === 'mods') resetCamera();
  sim.data.qvel.fill(0); sim.accumulator = 0;
  if (mode === 'live' && lastPacket && performance.now()-lastPacketAt<2500) liveResult = sim.applyTelemetry(lastPacket, $('live-source').value);
  updateModeText();
}

function applyPreset(preset) {
  setMode('pose'); running = false; gait = false; gaitTime = 0;
  sim.reset(preset); updateModeText(); $('pose-message').textContent = `${preset.toLowerCase()} pose loaded.`;
}

function startGait() {
  setMode('pose'); sim.reset('STAND'); gait = true; running = true;
  updateModeText();
}

function startDrop() {
  wheelsExploded = false; sim.drop(); running = true; updateModeText();
}

function startSkateRoll() {
  wheelsExploded = false;
  sim.reset();
  if (!demoMode) $('hold').checked = true;
  sim.setHold(true);
  sim.data.qvel[0] = .28;
  running = true;
  resetCamera();
  updateModeText();
}

async function prepareSkates() {
  if (skateSim) return;
  skateLoad ??= DuckSimulation.create(undefined, {skates:true}).then(loaded => {
    if (stopping) loaded.dispose();
    else skateSim = loaded;
  }).finally(() => { skateLoad = null; });
  await skateLoad;
}

function useSimulation(next) {
  const nextSim = next === 'skates' ? skateSim : stockSim;
  if (sim === nextSim) return;
  clearRobot();
  sim = nextSim;
  sim.setHold($('hold').checked);
  sim.setGravity(Number($('gravity').value));
  sim.setFriction(Number($('friction').value));
  if (sim.skates) sim.setSurface(demoMode ? 'flat' : $('skate-surface').value);
  buildRobot();
}

async function showDemoScene(name, preset, signal) {
  if (name === 'skates') {
    const report = await loadSkateSpeed();
    signal.throwIfAborted();
    playSkateSpeed(report);
    return;
  }
  signal.throwIfAborted();
  useSimulation(name);
  if (name === 'pose') applyPreset(preset);
  else if (name === 'gait') startGait();
  else if (name === 'drop') { setMode('physics'); startDrop(); }
  else setMode(name);
}

function updateDemoStatus(message, progress, active) {
  $('demo-state').textContent = message;
  $('demo-progress').textContent = progress;
  $('demo-toggle').textContent = active ? 'Stop demo' : 'Start demo';
  if (demoMode && !active) running = false;
}

async function selectWorkspace(next) {
  if (next === 'demo' && demoMode) return;
  const request = ++workspaceRequest;
  if (next !== 'demo') {
    demoMode = false;
    demo.stop();
  }
  if (next === 'mods' && !modPreview) {
    try {
      modLoad ??= loadModPreview().then(group => { modPreview = group; scene.add(group); })
        .finally(() => { modLoad = null; });
      await modLoad;
    } catch (error) {
      if (request === workspaceRequest) showError(error);
      return;
    }
    if (stopping || request !== workspaceRequest) return;
  }
  const useSkates = next === 'skates' || (next === 'mods' && $('mod-skates').checked);
  if (useSkates && !skateSim) {
    $('loading-message').textContent = 'Loading the roller skate model…';
    $('loading').hidden = false;
    try {
      await prepareSkates();
    } catch (error) {
      if (request === workspaceRequest) showError(error);
      return;
    } finally {
      if (request === workspaceRequest) $('loading').hidden = true;
    }
    if (stopping || request !== workspaceRequest) return;
  }
  $('loading').hidden = true;
  useSimulation(useSkates ? 'skates' : next);
  if (next === 'demo') {
    demoMode = true;
    setMode('pose');
    updateDemoStatus('Starting the demo…', 'LOOP', true);
    void demo.start();
  } else {
    setMode(next);
    if (next === 'mods') {
      await updateTailSelection();
      if (request !== workspaceRequest || stopping) return;
      updateMods();
      await updateModCosmetics();
    }
    if (next === 'replay' && replay.trial) await showReplayTrial('case');
  }
}

let dockIndex;
async function readReplayJson(path) {
  const response = await fetch(new URL(path, import.meta.url), {signal:AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error(`Replay download failed (HTTP ${response.status}).`);
  return response.json();
}

const skateSpeedRecordings = new Map();
async function loadSkateSpeed(terrainSweep = false) {
  const file = terrainSweep ? 'skate-terrain-recording.json' : 'skate-speed-recording.json';
  const [report] = await Promise.all([
    skateSpeedRecordings.get(file) ?? readReplayJson(`./${file}?v=1`), prepareSkates(),
  ]);
  skateSpeedRecordings.set(file, report);
  return report;
}

function skateTrial(recording) {
  const {profile, command_m_s, clean, total, median_m_s, trials} = recording.ranked[0];
  const worst_drift_m = Math.max(...trials.map(trial => trial.max_side_m));
  return {...recording.winner, skate:{profile, command_m_s, clean, total, median_m_s, worst_drift_m, terrain:recording.terrain}};
}

function playSkateSpeed(report, terrainSweep = false) {
  const flat = 'Six-second flat-floor run';
  const cases = terrainSweep ? Object.fromEntries(Object.values(report).filter(item => item.winner)
    .map(item => [item.terrain.label, skateTrial(item)])) : {[flat]: skateTrial(report)};
  const recording = {'Fastest clean policy': cases};
  if (!terrainSweep) recording['Previous passive push'] = {[flat]: {...report.baseline, skate:{profile:'Passive push'}}};
  setMode('replay');
  replay.setRecording(recording, {alternate:terrainSweep, cycleCases:terrainSweep});
  running = true;
  updateModeText();
}

async function openSkateSpeed(terrainSweep = false) {
  const request = ++workspaceRequest;
  try {
    const report = await loadSkateSpeed(terrainSweep);
    if (stopping || request !== workspaceRequest) return;
    playSkateSpeed(report, terrainSweep);
  } catch (error) {
    if (request === workspaceRequest && !stopping) showError(error);
  }
}

async function openStockReplay() {
  await selectWorkspace('replay');
  const status = $('qualification-status');
  status.textContent = 'Loading stock trials…';
  try {
    const report = await readReplayJson('./stock-replay.json');
    if (stopping) return;
    replay.setRecording(report, {scenario:query.get('trial'), variant:'stock'});
    running = true;
    updateModeText();
  } catch (error) {
    status.textContent = error.message;
  }
}

async function openDockReplay(variant, scenario = 'Skate turnaround trials') {
  await selectWorkspace('replay');
  if (mode !== 'replay' || stopping) return;
  const request = workspaceRequest;
  const fileRequest = replay.fileRequest;
  const status = $('qualification-status');
  status.textContent = 'Loading the dock trials…';
  try {
    dockIndex ??= await readReplayJson('./dock-recording-index.json?v=1');
    if (!Object.hasOwn(dockIndex, scenario)) scenario = Object.keys(dockIndex)[0];
    const dockLoader = name => loadDockCase(dockIndex, name,
      source => readReplayJson(`./${source}-recording.json?v=10`));
    const report = await dockLoader(scenario);
    if (stopping || request !== workspaceRequest || fileRequest !== replay.fileRequest) return;
    replay.setRecording(report, {scenario, variant:variant ?? SKATE_TURN_LOOP[0], alternate:!variant, dockIndex, dockLoader});
    running = true;
    updateModeText();
  } catch (error) {
    if (request === workspaceRequest && fileRequest === replay.fileRequest) status.textContent = error.message;
  }
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

function animateWalk(dt) {
  const packet = rolloutPacket();
  const root = packet?.root;
  const angles = packet?.joints_rad;
  searchWorld.visible = mode === 'explore' && Boolean(packet?.mission);
  if (!root || root.length !== 7 || !root.every(Number.isFinite)
      || !sim.joints.every(joint => Number.isFinite(angles?.[joint.id]))) return;
  const q = sim.data.qpos;
  const newRun = packet.run_id !== walkRun;
  const alpha = newRun ? 1 : 1 - Math.exp(-dt / 0.055);
  const dx = (root[0] - q[0]) * alpha, dy = (root[1] - q[1]) * alpha;
  q[0] += dx; q[1] += dy; q[2] += (root[2] - q[2]) * alpha;
  walkRotation.set(q[4], q[5], q[6], q[3]);
  walkTarget.set(root[4], root[5], root[6], root[3]);
  walkRotation.slerp(walkTarget, alpha).normalize();
  q[3] = walkRotation.w; q[4] = walkRotation.x; q[5] = walkRotation.y; q[6] = walkRotation.z;
  for (const joint of sim.joints) q[joint.address] += (angles[joint.id] - q[joint.address]) * alpha;
  sim.mj.mj_forward(sim.model, sim.data);
  if (newRun) {
    resetCamera();
    if (packet.mission) buildSearchArena(packet.mission.walls);
  } else if (mode === 'walk') {
    orbit.target.x += dx; orbit.target.y += dy;
    camera.position.x += dx; camera.position.y += dy;
  }
  if (packet.mission) {
    const {beacon, waypoint} = packet.mission;
    searchBeacon.visible = Boolean(beacon);
    searchWaypoint.visible = !beacon && Boolean(waypoint);
    if (beacon) searchBeacon.position.set(...beacon, .14);
    if (waypoint) searchWaypoint.position.set(...waypoint, .018);
  }
  walkRun = packet.run_id;
}

function rolloutPacket() {
  const sample = walk.latest;
  return Boolean(sample?.arena) === (mode === 'explore') ? sample : null;
}

function updateReplayModules(modules = [], dock) {
  for (const {mesh} of replayModules) {
    scene.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
  }
  replayModules = [];
  if (dock?.contact_force_n && typeof dock.approach_reached === 'boolean' && Number.isFinite(dock.seat_trigger_m)) {
    modules = [...modules, {name:'Lowering line', parent:'world',
      center_m:[dock.seat_trigger_m,0,.0007], size_m:[.002,.14,.001]}];
  }
  if (dock?.navigation) {
    const path = replay.trial.result.trace
      .filter(f => ['turn_around','brake_turn','reverse_seek'].includes(f.recovery.phase))
      .map(f => new THREE.Vector3(f.root[0], f.root[1], .0014));
    const color = '#65ccb7';
    const mesh = new THREE.Line(new THREE.BufferGeometry().setFromPoints(path), new THREE.LineBasicMaterial({color}));
    scene.add(mesh);
    replayModules.push({mesh, parent:0, name:'Recorded path', color});
    const marks = Array.from({length:8}, (_, i) => ({name:'Lane centre', parent:'world',
      center_m:[.105+i*.04,0,.0006], size_m:[.020,.002,.001]}));
    modules = [...modules, ...marks];
  }
  for (const module of modules) {
    const parent = module.parent === 'world' ? 0 : sim.mj.mj_name2id(sim.model, sim.mj.mjtObj.mjOBJ_BODY.value, module.parent);
    if (parent < 0) continue;
    let geometry;
    if (module.capsule_m) {
      const [radius, length] = module.capsule_m;
      geometry = new THREE.CapsuleGeometry(radius, length - 2 * radius, 5, 12);
      geometry.rotateX(Math.PI / 2);
    } else geometry = dockSurfaceGeometry(module);
    geometry.translate(...module.center_m);
    const color = module.name.endsWith(' contact') ? '#c99a5e'
      : module.name === 'Trip bar' ? '#f17242' : ['Lane centre', 'Lowering line'].includes(module.name) ? '#6fd6ff' : module.name.endsWith('entry rail') ? '#4cb6a6' : '#7295f4';
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({color}));
    mesh.matrixAutoUpdate = false;
    scene.add(mesh);
    replayModules.push({mesh, parent, name:module.name, color});
  }
}

function navigationLabel(frame, navigation) {
  const phase = frame?.recovery?.phase;
  if (phase === 'brake_turn') return 'Braking for reverse';
  if (phase === 'turn_around' || phase === 'reverse_seek') {
    const [, y, , w, qx, qy, qz] = frame.root;
    const yaw = Math.atan2(2*(w*qz+qx*qy), 1-2*(qy*qy+qz*qz));
    return phase === 'turn_around' ? `Turn around · ${Math.round(yaw*180/Math.PI)}°`
      : `Seek backwards · ${Math.round(Math.abs(y)*1000)} mm off centre`;
  }
  return phase === 'approach_missed' ? navigation.outcome : replay.selectedLabel;
}

function applyReplayPose() {
  const packet = replay.frame;
  if (!packet || packet === lastReplayPose || usesSkates(replay.trial.result) !== Boolean(sim.skates)) return;
  lastReplayPose = packet;
  if (replay.trial.result.dock?.navigation) $('scene-mode').textContent = navigationLabel(packet, replay.trial.result.dock.navigation);
  const contact = $('dock-contact-overlay');
  const pushOff = Array.isArray(packet.push_off) ? packet.push_off.join(' · ') : '';
  contact.hidden = !replay.trial.result.dock || !pushOff;
  if (contact.textContent !== pushOff) contact.textContent = pushOff;
  const data = sim.data, q = data.qpos;
  const dx = packet.root[0] - q[0], dy = packet.root[1] - q[1];
  if (replay.trial.result.skate) {
    const distance = packet.root[0] - replay.trial.result.trace[0].root[0];
    const label = `${distance.toFixed(2)} m`;
    if ($('skate-distance').textContent !== label) $('skate-distance').textContent = label;
  }
  q.set(packet.root, 0);
  for (const joint of sim.joints) q[joint.address] = packet.joints_rad[joint.id];
  for (const [index, address] of sim.wheelPositions.entries()) q[address] = packet.wheels_rad[index];
  sim.mj.mj_forward(sim.model, data);
  for (const {mesh, parent, name, color} of replayModules) {
    const a = data.xmat, b = data.xpos, m = parent * 9, p = parent * 3;
    mesh.matrix.set(a[m],a[m+1],a[m+2],b[p], a[m+3],a[m+4],a[m+5],b[p+1],
                    a[m+6],a[m+7],a[m+8],b[p+2], 0,0,0,1);
    mesh.matrixWorldNeedsUpdate = true;
    const contacts = packet.module_contacts;
    mesh.material.color.set(Array.isArray(contacts) && contacts.includes(name) ? '#edc16f' : color);
  }
  if (typeof replay.trial.result.dock?.approach_reached !== 'boolean') {
    orbit.target.x += dx; orbit.target.y += dy;
    camera.position.x += dx; camera.position.y += dy;
    const dz = sprintGroundHeight(replay.trial.result.skate?.terrain, dx, dy);
    orbit.target.z += dz; camera.position.z += dz;
  }
}

async function showReplayTrial(action) {
  if (mode !== 'replay') return;
  const trial = replay.trial;
  const skates = usesSkates(trial.result);
  if (action === 'seek' || (action === 'case' && !trial.result.dock && !trial.result.skate)) running = false;
  if (skates && !skateSim) {
    try { await prepareSkates(); }
    catch (error) {
      if (mode === 'replay' && replay.trial === trial) showError(error);
      return;
    }
    if (stopping || mode !== 'replay' || replay.trial !== trial) return;
  }
  const modelChanged = Boolean(skates) !== Boolean(sim.skates);
  if (modelChanged) {
    useSimulation(skates ? 'skates' : 'replay');
    if (skates) sim.setSurface('flat');
    sim.mode = 'replay';
  }
  if (action !== 'seek' || modelChanged) {
    lastReplayPose = null;
    updateReplayModules(trial.modules, trial.result.dock);
  }
  applyReplayPose();
  if (action === 'case' || modelChanged) resetCamera();
  updateModeText();
}

function buildSearchArena(walls) {
  searchWorld.clear();
  searchWorld.add(searchBeacon, searchWaypoint);
  for (const [x, y, width, depth] of walls) {
    const wall = new THREE.Mesh(wallGeometry, wallMaterial);
    wall.position.set(x, y, .13);
    wall.scale.set(width, depth, .26);
    searchWorld.add(wall);
  }
}

async function updateTailSelection() {
  const generation = ++tailGeneration;
  if ($('mod-tail').checked && !tailPreview) {
    $('mod-tail-play').disabled = true;
    $('mod-tail-note').textContent = 'Loading the tail assembly…';
    try {
      tailLoad ??= import('./tail-preview.mjs?v=2').then(module => module.loadTailPreview())
        .then(loaded => {
          tailPreview = loaded;
          loaded.group.visible = false;
          modPreview.add(loaded.group);
        }).catch(error => { tailLoad = null; throw error; });
      await tailLoad;
    } catch (error) {
      if (generation === tailGeneration) {
        $('mod-tail-note').textContent = error.message;
        $('mod-mass').textContent = 'Tail geometry unavailable.';
      }
      return;
    }
  }
  if (stopping || generation !== tailGeneration || mode !== 'mods') return;
  syncTailPlayback();
  updateMods();
}

function syncTailPlayback() {
  const selected = mode === 'mods' && $('mod-tail').checked;
  const matches = selected && !sim.skates && !$('mod-teeth').checked && !$('mod-tusks').checked;
  $('mod-tail-play').disabled = !matches || !tailPreview?.hasTrace;
  const play = !$('mod-tail-play').disabled && $('mod-tail-play').checked;
  if (!matches) $('mod-tail-play').checked = false;
  if (tailPlaying && !play) {
    sim.reset('STAND');
    tailPreview?.rest();
    if (mode === 'mods') resetCamera();
  }
  if (!tailPlaying && play) tailClock = 0;
  tailPlaying = play;
  if (selected && tailPreview) $('mod-tail-note').textContent = matches
    ? tailPreview.trialText : 'Static fit preview. The recorded trial uses stock feet and the stock head.';
}

function updateMods() {
  const tail = $('mod-tail').checked;
  const pack = $('mod-pack').checked;
  if (modPreview) {
    showModLayers(modPreview, pack, $('mod-trace').checked);
    if (tail) {
      modPreview.getObjectByName('rails').visible = true;
      $('mod-mass').textContent = tailPreview?.massText || 'Loading tail mass estimate…';
    } else showModMass(modPreview.userData.harness, pack);
  }
  $('mod-tail-controls').hidden = !tail;
  $('mod-pack-id').hidden = !(tail || pack);
  if (tailPreview) tailPreview.group.visible = tail;
  for (const id of ['mod-bill', 'mod-trace-label']) $(id).hidden = !pack;
  $('mod-routing').hidden = !pack || !$('mod-trace').checked;
  updateModStatus();
}

async function updateModCosmetics({focus = false} = {}) {
  const request = ++modRequest;
  const teeth = $('mod-teeth').checked, tusks = $('mod-tusks').checked;
  const pattern = $('mod-skin').value;
  $('mod-skin-note').hidden = pattern === 'plain';
  $('mod-tusk-camera').hidden = !tusks;
  $('mod-jaw-mass').hidden = !teeth && !tusks;
  $('mod-jaw-mass').textContent = 'Jaw mass estimate pending.';
  updateModStatus();
  try {
    if (teeth || tusks) {
      dinoLoad ??= import('./dino-preview.mjs?v=3').then(async module => {
        const group = await module.loadDinoPreview();
        dino = group;
        dinoModule = module;
        dino.visible = false;
        scene.add(dino);
      }).catch(error => { dinoLoad = null; throw error; });
      await dinoLoad;
    }
    if (pattern !== 'plain') skinModule ??= await import('./skin-preview.mjs');
    if (stopping || request !== modRequest || mode !== 'mods') return;
    if (appliedSkin !== pattern) {
      if (pattern !== 'plain' && !teeth && !tusks && !$('mod-pack').checked) setHardwareCamera('side');
      skinModule?.setShellSkin(visualMeshes, sim, pattern);
      appliedSkin = pattern;
    }
    if (dino) {
      if (appliedJawSkin !== pattern) {
        const panels = [];
        dino.traverse(mesh => { if (mesh.userData.meshName === 'head_roll') panels.push(mesh); });
        skinModule?.setShellSkin(panels, sim, pattern);
        appliedJawSkin = pattern;
      }
      dino.visible = teeth || tusks;
      if (dino.visible) {
        updateJaw(performance.now() / 1000);
        const mass = dino.userData.massByVariant?.[teeth && tusks ? 'combined' : teeth ? 'teeth' : 'tusks'];
        if (mass && Number.isFinite(mass.nominal)) {
          $('mod-jaw-mass').textContent = 'Jaw change · ' + mass.nominal.toFixed(2) +
            ' g estimated (' + mass.low.toFixed(2) + '–' + mass.high.toFixed(2) + ' g).';
        }
        if (focus) setJawCamera();
      }
    }
    for (const mesh of visualMeshes) {
      if (mesh.userData.meshName === 'head_roll') mesh.visible = !dino?.visible || !dino.userData.replacesHeadRoll;
    }
  } catch (error) {
    if (request === modRequest) showError(error);
  }
}

function updateJaw(seconds) {
  if (!dino?.visible || jawBody < 0) return;
  const {xpos, xquat} = sim.data;
  dino.position.fromArray(xpos, jawBody * 3);
  const j = jawBody * 4;
  dino.quaternion.set(xquat[j + 1], xquat[j + 2], xquat[j + 3], xquat[j]);
  dinoModule.updateDinoPreview(dino, seconds, {teeth: $('mod-teeth').checked, tusks: $('mod-tusks').checked});
}

function showModMass(harness, pack) {
  if (!pack) {
    $('mod-mass').textContent = 'Stock V5 enclosure. Geometry preview only.';
    return;
  }
  const parts = harness.parts;
  const groups = [
    ['Rails and cover', harness.printed.map(part => part.mass_g)],
    ['Insulated leads', harness.leads.map(lead => lead.mass_g)],
    ['Fixed contacts', parts.filter(part => part.id.startsWith('pad-')).map(part => part.mass_g)],
    ['Connector halves', parts.filter(part => part.id.startsWith('disconnect-')).map(part => part.mass_g)],
    ['Charge plug', parts.filter(part => part.id === 'plug-envelope').map(part => part.mass_g)],
    ['Keyed isolator', parts.filter(part => part.id === 'keyed-isolator').map(part => part.mass_g)],
    ['Tray and mount', parts.filter(part => part.kind === 'mount').map(part => part.mass_g)],
    ['Strain relief', parts.filter(part => part.id.startsWith('relief-')).map(part => part.mass_g)],
  ];
  const total = harness.estimate.with_printed.mass_g;
  $('mod-mass').textContent = 'Wired backpack · ' + total.nominal.toFixed(1) + ' g (' +
    total.low.toFixed(1) + '–' + total.high.toFixed(1) + ' g). Robot-side parts only.';
  const rows = groups.map(([label, masses]) => {
    const nominal = masses.reduce((sum, mass) => sum + mass.nominal, 0);
    const row = document.createElement('div');
    const term = document.createElement('dt'), value = document.createElement('dd');
    term.textContent = label;
    value.textContent = nominal.toFixed(2) + ' g';
    row.append(term, value);
    return row;
  });
  $('mod-components').replaceChildren(...rows);
}

function updateModStatus() {
  const pack = $('mod-pack').checked;
  const packet = lastPacket && performance.now() - lastPacketAt < 2500 ? lastPacket : null;
  const result = modPolicyStatus(pack, $('mod-skates').checked, packet, undefined, {
    teeth: $('mod-teeth').checked, tusks: $('mod-tusks').checked, tail: $('mod-tail').checked,
  });
  const status = $('mod-status');
  if (status.textContent !== result.text) status.textContent = result.text;
  status.style.color = ['matched', 'transfer'].includes(result.state) ? 'var(--mint)' : 'var(--amber)';
  $('mod-board').textContent = packet ? 'Board · ' + packet.mode + ' · ' + (packet.active_model || 'no active model') : 'Board telemetry offline';
}

function updateBoard() {
  if (mode === 'mods') updateModStatus();
  const fresh = lastPacket && performance.now() - lastPacketAt < 2500;
  $('board-dot').style.background = fresh ? '#8edac8' : '#edc16f';
  $('board-state').textContent = fresh ? 'Connected' : 'Not connected';
  $('board-feedback').textContent = fresh ? `${lastPacket.feedback_hz.toFixed(1)} Hz` : '—';
  $('board-servos').textContent = fresh ? `${lastPacket.servo_ids?.length || 0}/15` : '—';
  const cpu = fresh ? lastPacket.cpu : null;
  $('board-cpu').textContent = cpu?.available && Number.isFinite(cpu.load_percent) ? `${cpu.load_percent.toFixed(1)}%` : '—';
  $('board-cpu').title = cpu?.available && Number.isFinite(cpu.busiest_core_percent) ? `Busiest core ${cpu.busiest_core_percent.toFixed(1)}%` : '';
  $('board-gpu').textContent = fresh && lastPacket.gpu?.available ? `${lastPacket.gpu.load_percent.toFixed(1)}%` : '—';
  $('board-missed').textContent = fresh && Number.isInteger(lastPacket.loop_missed) ? lastPacket.loop_missed : '—';
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
    let current = null;
    try {
      const response = await fetch('/api/status', {cache:'no-store', signal:AbortSignal.timeout(1800)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const packet = await response.json();
      if (typeof packet.feedback_hz !== 'number') throw new Error('Invalid telemetry');
      lastPacket = packet; lastPacketAt = performance.now();
      current = packet;
      if (sim && mode === 'live' && running) liveResult = sim.applyTelemetry(packet, $('live-source').value);
    } catch { /* The age check replaces stale readings with unavailable indicators. */ }
    if (rolloutMode(mode)) walk.recordBoard(current);
  }
  updateBoard();
  setTimeout(pollBoard, mode === 'live' && !document.hidden ? 200 : 1000);
}

function attachControls() {
  for (const id of ['mod-pack','mod-tail']) {
    $(id).addEventListener('change', async () => {
      if ($(id).checked) $(id === 'mod-tail' ? 'mod-pack' : 'mod-tail').checked = false;
      updateMods();
      await updateTailSelection();
      if (mode === 'mods' && id === 'mod-tail' && $('mod-tail').checked) setTailCamera();
    });
  }
  $('mod-tail-play').addEventListener('change', syncTailPlayback);
  $('mod-trace').addEventListener('change', updateMods);
  for (const id of ['mod-teeth', 'mod-tusks', 'mod-skin']) {
    $(id).addEventListener('change', () => {
      syncTailPlayback();
      void updateModCosmetics({focus: id !== 'mod-skin'});
    });
  }
  $('mod-skates').addEventListener('change', () => void selectWorkspace('mods'));
  document.querySelectorAll('[data-mode]').forEach(button => { button.disabled=false; button.addEventListener('click', () => selectWorkspace(button.dataset.mode)); });
  $('demo-toggle').addEventListener('click', () => {
    if (demo.controller) demo.stop();
    else void demo.start();
  });
  $('physics-controller').addEventListener('change', event => setMode(event.target.value));
  document.querySelectorAll('[data-preset]').forEach(button => { button.disabled = false; button.addEventListener('click', () => applyPreset(button.dataset.preset)); });
  for (const id of ['reset','camera','gait','export','import']) $(id).disabled = false;
  $('reset').addEventListener('click', () => {
    if (mode === 'replay') { replay.seek(0); return; }
    wheelsExploded = false;
    sim.reset('STAND'); gaitTime = 0;
    if (mode === 'pose' || mode === 'skates') { gait=false; running=false; }
    if (mode === 'skates') resetCamera();
    updateModeText();
  });
  $('camera').addEventListener('click', resetCamera);
  $('dock-overhead').addEventListener('click', () => {
    dockOverhead = !dockOverhead;
    resetCamera();
    updateModeText();
  });
  for (const button of document.querySelectorAll('[data-hardware-camera]')) {
    button.addEventListener('click', () => setHardwareCamera(button.dataset.hardwareCamera));
  }
  $('hardware-test-pattern').addEventListener('change', event => guardPreview.setTestPattern(event.target.checked));
  const dockDesign = $('dock-design');
  dockDesign.replaceChildren(...DOCK_DESIGNS.map(name => new Option(name, name)));
  dockDesign.value = 'Fixed pad chair';
  dockDesign.addEventListener('change', () => guardPreview.setDockDesign(dockDesign.value));
  $('dock-replay').addEventListener('click', () => void openDockReplay(dockDesign.value, 'Centred entry'));
  const assemblies = document.querySelectorAll('[data-assembly]');
  const hardwareNotes = {
    cutout: 'The faceplate shields the carrier. Its opening lines up with the carrier’s existing matrix cut-out.',
    translucent: 'The optional translucent window covers the display opening. Air can still pass around the open edges.',
    exploded: 'The shroud and blue carrier separate to expose the inner UNO Q, its matrix and the mated headers.',
    dock: 'Compare flat trays and chairs. Play a trial to see how the Duck settles, rises and clears the dock.',
  };
  for (const button of assemblies) {
    button.addEventListener('click', () => {
      const assembly = button.dataset.assembly;
      guardPreview.show(assembly);
      $('dock-controls').hidden = assembly !== 'dock';
      if (assembly === 'dock') guardPreview.setDockDesign(dockDesign.value);
      for (const option of assemblies) option.setAttribute('aria-pressed', String(option === button));
      $('hardware-note').textContent = hardwareNotes[assembly];
      const changedMountView = assemblyCamera(hardwareAssembly) !== assemblyCamera(assembly);
      hardwareAssembly = assembly;
      if (changedMountView) resetCamera();
    });
  }
  $('play').addEventListener('click', () => {
    if (mode === 'replay' && !running && replay.time >= replay.duration) replay.seek(0);
    wheelsExploded = false;
    running = !running; sim.accumulator = 0; updateModeText();
  });
  $('roll-forward').addEventListener('click', startSkateRoll);
  $('skate-speed').addEventListener('click', () => void openSkateSpeed());
  $('skate-terrain-speed').addEventListener('click', () => void openSkateSpeed(true));
  $('skate-surface').addEventListener('change', event => {
    sim.setSurface(event.target.value);
    sim.reset();
    wheelsExploded = running = false;
    resetCamera();
    updateModeText();
  });
  $('start-tow').addEventListener('click', () => {
    wheelsExploded = false;
    sim.startTow($('tow-mount').value);
    $('hold').checked = true;
    running = true;
    resetCamera();
    updateModeText();
  });
  $('explode-wheels').addEventListener('click', () => {
    wheelsExploded = !wheelsExploded;
    running = false;
    updateModeText();
  });
  $('gait').addEventListener('click', () => {
    if (gait) { gait = false; running = false; updateModeText(); }
    else startGait();
  });
  $('drop').addEventListener('click', startDrop);
  $('nudge').addEventListener('click', () => sim.nudge());
  $('step').addEventListener('click', () => { if (!running && playground(mode) && !wheelsExploded) sim.step(10); });
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
      await selectWorkspace('pose'); sim.applyPose(angles); updateRows();
      $('pose-message').textContent = 'Pose loaded locally. No motor commands sent.';
    } catch (error) { $('pose-message').textContent = error.message; }
    $('pose-file').value = '';
  });
  viewport.addEventListener('keydown', event => {
    if (event.code === 'Space' && !$('play').disabled && !$('play').hidden) { event.preventDefault(); $('play').click(); }
  });
  const canvas = renderer.domElement;
  let tap = null;
  const moved = event => Math.hypot(tap.x - event.clientX, tap.y - event.clientY) > 5;
  canvas.addEventListener('pointerdown', event => {
    tap = event.isPrimary && event.button === 0 ? {id: event.pointerId, x: event.clientX, y: event.clientY} : null;
  });
  canvas.addEventListener('pointermove', event => {
    if (tap?.id === event.pointerId && moved(event)) tap = null;
  });
  canvas.addEventListener('pointercancel', () => { tap = null; });
  canvas.addEventListener('lostpointercapture', () => { tap = null; });
  canvas.addEventListener('pointerup', event => {
    const pick = tap?.id === event.pointerId && !moved(event);
    tap = null;
    if (!pick || mode === 'hardware' || mode === 'mods') return;
    const rect = canvas.getBoundingClientRect();
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
    if (running && playground(mode)) sim.advance(dt*Number($('speed').value));
    if (running && mode === 'pose' && gait) animateGait(dt);
    if (rolloutMode(mode)) animateWalk(dt);
    if (mode === 'replay') {
      const result = replay.trial?.result;
      if (running && !replay.advance(dt, Boolean(result?.dock || (result?.skate && !demoMode)))) { running = false; updateModeText(); }
      applyReplayPose();
    }
    if (mode === 'hardware') guardPreview.followTrunk(sim.data.qpos);
    if (mode === 'mods') {
      if (tailPlaying) {
        const oldX = sim.data.qpos[0], oldY = sim.data.qpos[1];
        tailClock += dt;
        tailPreview.play(sim, tailClock);
        const dx = sim.data.qpos[0] - oldX, dy = sim.data.qpos[1] - oldY;
        camera.position.x += dx; camera.position.y += dy;
        orbit.target.x += dx; orbit.target.y += dy;
      }
      const q = sim.data.qpos;
      modPreview.position.fromArray(q);
      modPreview.quaternion.set(q[4], q[5], q[6], q[3]);
      updateJaw(time / 1000);
    }
    updateSkateScene();
    updateRobot(); orbit.update(); renderer.render(scene,camera);
    fpsFrames++;
    if (time-fpsStart>600) { fps=fpsFrames*1000/(time-fpsStart); fpsFrames=0; fpsStart=time; }
    if (time-lastHud>200) {
      $('fps').textContent = Math.round(fps);
      $('sim-time').textContent = (mode === 'replay' ? replay.time : rolloutMode(mode) ? rolloutPacket()?.time_s ?? 0 : gait ? gaitTime : sim.data.time).toFixed(2);
      $('contacts').textContent = mode === 'replay' ? replay.frame?.contacts ?? '—'
        : rolloutMode(mode) ? rolloutPacket()?.contacts ?? '—' : playground(mode) ? sim.data.ncon : '—';
      $('height').textContent = (sim.data.qpos[2]*100).toFixed(1);
      if (mode === 'skates') {
        const tow = sim.tow;
        $('tow-status').textContent = tow
          ? `${tow.status} · ${tow.tension.toFixed(2)} N · peak ${tow.peak.toFixed(2)} N`
          : 'The simulated hitch releases at 1.5 N.';
      }
      updateRows(); updateBoard(); lastHud=time;
    }
  } catch (error) { demo.stop(); running=false; updateModeText(); showError(error); }
}

async function start() {
  scene = new THREE.Scene(); scene.background = new THREE.Color('#0c1720');
  const verticalFov = 36;
  camera = new THREE.PerspectiveCamera(verticalFov,1,0.005,12); camera.up.set(0,0,1);
  renderer = new THREE.WebGPURenderer({antialias:true, alpha:false});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1,1.5));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  await renderer.init();
  const webgpu = Boolean(renderer.backend.isWebGPUBackend);
  $('renderer-state').textContent = webgpu ? 'WEBGPU · CLIENT GPU' : 'WEBGL 2 · FALLBACK';
  $('engine-note').textContent = webgpu ? 'WebGPU graphics on this viewing device · Playground physics in browser · Walking policy on UNO Q'
    : `${window.isSecureContext ? 'This browser selected WebGL 2.' : 'Wi-Fi HTTP uses WebGL 2; open localhost over USB for WebGPU.'} The walking policy runs on the UNO Q CPU.`;
  viewport.prepend(renderer.domElement);
  orbit = new OrbitControls(camera,renderer.domElement);
  orbit.enableDamping = true;
  orbit.touches.ONE = THREE.TOUCH.ROTATE;
  orbit.touches.TWO = THREE.TOUCH.DOLLY_PAN;
  orbit.minDistance=0.15; orbit.maxDistance=1.8; orbit.maxPolarAngle=Math.PI*0.49; resetCamera();
  scene.add(new THREE.HemisphereLight('#e8f9ff','#294443',2.6));
  const light = new THREE.DirectionalLight('#fff3db',3.2); light.position.set(-0.3,-0.4,0.8); scene.add(light);
  const fill = new THREE.DirectionalLight('#8edac8',1.8); fill.position.set(0.5,0.25,0.4); scene.add(fill);
  floorGroup = new THREE.Group();
  ground = new THREE.Mesh(new THREE.PlaneGeometry(16,16),new THREE.MeshStandardMaterial({color:'#15252c',roughness:0.95}));
  ground.position.z=-0.0005;
  grid = new THREE.GridHelper(14,280,'#47606b','#243b46'); grid.rotation.x=Math.PI/2; grid.position.z=0.0001;
  floorGroup.add(ground, grid); scene.add(floorGroup);
  const axes = new THREE.AxesHelper(0.05); axes.position.set(-0.16,-0.13,0.001); scene.add(axes);
  searchWorld = new THREE.Group();
  searchWorld.visible = false;
  wallGeometry = new THREE.BoxGeometry(1,1,1);
  wallMaterial = new THREE.MeshStandardMaterial({color:'#657d91', roughness:.7, transparent:true, opacity:.68, depthWrite:false});
  searchBeacon = new THREE.Mesh(new THREE.SphereGeometry(.068,16,12), new THREE.MeshBasicMaterial({color:'#ffcb72'}));
  searchWaypoint = new THREE.Mesh(new THREE.SphereGeometry(.022,12,8), new THREE.MeshBasicMaterial({color:'#90aafa'}));
  scene.add(searchWorld);
  buildSkateScene();
  const resize = new ResizeObserver(() => {
    const width = viewport.clientWidth, height = viewport.clientHeight;
    if (!width || !height) return;
    camera.aspect = width / height;
    const aspectScale = Math.max(1, .55 / camera.aspect);
    camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(verticalFov / 2)) * aspectScale));
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
  }); resize.observe(viewport);
  sim = stockSim = await DuckSimulation.create();
  replay = new QualificationReplay($('qualification-card'), sim.joints.map(joint => joint.id), showReplayTrial);
  buildRobot(); buildJointControls(); attachControls(); updateModeText(); updateRobot();
  await renderer.compileAsync(scene,camera);
  $('loading').hidden=true;
  renderer.setAnimationLoop(frame);
  pollBoard();
  window.addEventListener('pagehide',event => {
    demo.pageHidden();
    if (event.persisted || stopping) return;
    stopping=true; walk.setVisible(false); resize.disconnect(); renderer.setAnimationLoop(null); orbit.dispose();
    clearRobot();
    wallGeometry.dispose(); wallMaterial.dispose();
    for (const marker of [searchBeacon, searchWaypoint]) { marker.geometry.dispose(); marker.material.dispose(); }
    updateReplayModules();
    for (const group of Object.values(terrain)) group.traverse(({geometry,material}) => {
      geometry?.dispose(); material?.dispose();
    });
    for (const marker of [towLine,towPoint,skateTrack]) { marker.geometry.dispose(); marker.material.dispose(); }
    for (const tile of sprintTiles.values()) { tile.geometry.dispose(); tile.material.dispose(); tile.dispose(); }
    guardPreview?.dispose();
    for (const group of [modPreview,dino].filter(Boolean)) {
      const geometries = new Set(), materials = new Set();
      group.traverse(mesh => { if (mesh.geometry) geometries.add(mesh.geometry); if (mesh.material) materials.add(mesh.material); });
      for (const item of [...geometries, ...materials]) item.dispose();
    }
    stockSim.dispose(); skateSim?.dispose(); renderer.dispose();
  });
  if (stockView) {
    if (query.get('run') === '1') await selectWorkspace('walk');
    else await openStockReplay();
  } else if (['mods', 'teeth', 'tusks', 'tail'].some(key => query.get(key) === '1') || query.has('skin')) {
    $('mod-teeth').checked = query.get('teeth') === '1' && !$('mod-teeth').parentElement.hidden;
    $('mod-tusks').checked = query.get('tusks') === '1' && !$('mod-tusks').parentElement.hidden;
    const skin = query.get('skin');
    if (['feather','orbit','chevron'].includes(skin)) $('mod-skin').value = skin;
    $('mod-tail').checked = query.get('tail') === '1';
    $('mod-tail-play').checked = $('mod-tail').checked && query.get('trial') === '1';
    $('mod-pack').checked = !$('mod-tail').checked && (query.has('pack') ? query.get('pack') === '1'
      : !($('mod-teeth').checked || $('mod-tusks').checked || skin));
    $('mod-skates').checked = query.get('skates') === '1';
    await selectWorkspace('mods');
  } else if (query.get('dock') === '1') {
    dockOverhead = query.get('view') === 'overhead' || (!query.has('view') && query.has('dock') &&
      (!query.has('entry') || query.get('entry') === 'Skate turnaround trials'));
    await openDockReplay(query.get('design') || undefined, query.get('entry') || undefined);
  } else if (query.get('hardware') === '1') {
    await selectWorkspace('hardware');
  }
  else if (query.get('sprint') === '1') await openSkateSpeed(query.get('terrain') === '1');
  else if (query.get('skates') === '1') selectWorkspace('skates');
  else if (query.get('replay') === '1') selectWorkspace('replay');
  else if (query.get('demo') === '1') selectWorkspace('demo');
}

if (!stockView) mountMatrixControls(() => !stopping);
start().catch(error => {
  $('loading').textContent = 'The 3D workspace could not start.';
  showError(error);
});
