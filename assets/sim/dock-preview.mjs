import * as THREE from 'three';
import floorDock from './floor-dock-designs.json?v=7' with {type:'json'};

export const DOCK_DESIGNS = [...Object.keys(floorDock.designs), ...Object.keys(floorDock.chairs ?? {})];

export function dockRampGeometry(size, angle) {
  const [length, width, height] = size;
  const halfRun = length / 2, halfHeight = height / 2;
  const rise = length * Math.tan(THREE.MathUtils.degToRad(angle));
  const shape = new THREE.Shape();
  shape.moveTo(-halfRun,-halfHeight);
  shape.lineTo(halfRun,-halfHeight);
  shape.lineTo(halfRun,halfHeight + Math.min(rise,0));
  shape.lineTo(-halfRun,halfHeight - Math.max(rise,0));
  shape.closePath();
  return new THREE.ExtrudeGeometry(shape, {depth:width, bevelEnabled:false})
    .rotateX(Math.PI / 2).translate(0,width / 2,0);
}

export function dockSurfaceGeometry({size_m, roll_deg = 0, pitch_deg = 0, yaw_deg = 0, ramp_deg}) {
  const geometry = ramp_deg ? dockRampGeometry(size_m, ramp_deg) : new THREE.BoxGeometry(...size_m);
  geometry.rotateX(THREE.MathUtils.degToRad(roll_deg));
  geometry.rotateY(THREE.MathUtils.degToRad(pitch_deg));
  geometry.rotateZ(THREE.MathUtils.degToRad(yaw_deg));
  return geometry;
}

// Packaging envelope only. Select the matched transmitter and receiver
// before turning these dimensions into tolerances or a charging gap.
const WIDTH = .028;
const HEIGHT = .044;
const CENTER_Y = -.015;
const CENTER_Z = -.021;
const RX_X = -.0794;

export function buildDockPreview() {
  const receiver = new THREE.Group(), dock = new THREE.Group();
  const wireless = new THREE.Group();
  receiver.add(wireless);
  const caseMaterial = new THREE.MeshStandardMaterial({color:'#17252d', roughness:.74});
  const ferrite = new THREE.MeshStandardMaterial({color:'#28363e', roughness:.82});
  const frame = new THREE.MeshStandardMaterial({color:'#435e72', roughness:.61});
  const guide = new THREE.MeshStandardMaterial({color:'#51909a', roughness:.68});
  const cap = new THREE.MeshStandardMaterial({
    color:'#acc9d1', transparent:true, opacity:.21, roughness:.64, depthWrite:false,
  });
  const copper = new THREE.MeshStandardMaterial({color:'#e49a63', roughness:.42, metalness:.42});

  function box(parent, material, size, center) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
    mesh.position.set(...center);
    parent.add(mesh);
    return mesh;
  }

  function winding(parent, point) {
    const points = [];
    for (let i = 0; i <= 192; i++) {
      const t = i/192, angle = t*Math.PI*12;
      const radius = .29 + .71*t;
      points.push(point(Math.cos(angle)*.012*radius, Math.sin(angle)*.018*radius));
    }
    parent.add(new THREE.Mesh(
      new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),192,.00027,5,false), copper));
  }

  // Show the coil through a ghosted service cap in this mechanical preview.
  box(wireless, ferrite, [.001,WIDTH-.002,HEIGHT-.002], [RX_X+.00065,CENTER_Y,CENTER_Z]);
  box(wireless, cap, [.0008,WIDTH,HEIGHT], [RX_X-.001,CENTER_Y,CENTER_Z]);
  for (const side of [-1,1]) {
    box(wireless, caseMaterial, [.0028,.0016,HEIGHT], [RX_X,CENTER_Y+side*(WIDTH/2-.0008),CENTER_Z]);
    box(wireless, caseMaterial, [.0028,WIDTH-.0032,.0016], [RX_X,CENTER_Y,CENTER_Z+side*(HEIGHT/2-.0008)]);
  }
  winding(wireless, (y,z) => new THREE.Vector3(RX_X,CENTER_Y+y,CENTER_Z+z));

  // Place the standing Duck beside the floor tray for inspection.
  dock.position.x = -.190;
  const layouts = new Map();
  const fixedReceivers = new Map();
  for (const name of DOCK_DESIGNS) {
    const layout = new THREE.Group();
    const chair = floorDock.chairs?.[name];
    const surfaces = chair ? chair.modules : [floorDock.deck, ...floorDock.designs[name]];
    for (const [index, surface] of surfaces.entries()) {
      const material = surface.name?.endsWith('seat contact') ? copper : index === 0 ? frame : guide;
      const mesh = new THREE.Mesh(dockSurfaceGeometry(surface), material);
      mesh.position.set(...surface.center_m);
      layout.add(mesh);
    }
    if (chair?.fixed_pads) {
      const pads = new THREE.Group();
      for (const pad of chair.shroud_pads) box(pads, copper, pad.size_m, pad.center_m);
      receiver.add(pads);
      fixedReceivers.set(name, pads);
    } else {
      const coil = new THREE.Group();
      coil.position.set(...(chair?.transmitter_m ?? floorDock.transmitter_m));
      coil.rotation.y = THREE.MathUtils.degToRad(chair?.transmitter_pitch_deg ?? chair?.backrest_deg ?? 0);
      coil.translateZ(.0016);
      box(coil, cap, [HEIGHT,WIDTH,.0005], [0,0,.0002]);
      winding(coil, (dy,dx) => new THREE.Vector3(dx,dy,0));
      layout.add(coil);
    }
    dock.add(layout);
    layouts.set(name, layout);
  }
  const setDesign = name => {
    for (const [design, layout] of layouts) layout.visible = name === design;
    for (const [design, pads] of fixedReceivers) pads.visible = name === design;
    wireless.visible = !fixedReceivers.has(name);
    dock.position.x = floorDock.chairs?.[name] ? -.245 : -.190;
  };
  setDesign('Low rails');
  receiver.visible = dock.visible = false;
  return {receiver,dock,setDesign};
}
