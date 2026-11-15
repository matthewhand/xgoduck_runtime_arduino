import * as THREE from 'three';

// Packaging envelope only. Select the matched transmitter and receiver
// before turning these dimensions into tolerances or a charging gap.
const WIDTH = .028;
const HEIGHT = .044;
const CENTER_Y = -.015;
const CENTER_Z = -.021;
const RX_X = -.0794;
const TX_X = -.0854;
const FLOOR_Z = -.139;

export function buildDockPreview() {
  const receiver = new THREE.Group(), dock = new THREE.Group();
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
  }

  function winding(parent, x) {
    const points = [];
    for (let i = 0; i <= 192; i++) {
      const t = i/192, angle = t*Math.PI*12;
      const radius = .29 + .71*t;
      points.push(new THREE.Vector3(x, CENTER_Y+Math.cos(angle)*.012*radius,
        CENTER_Z+Math.sin(angle)*.018*radius));
    }
    parent.add(new THREE.Mesh(
      new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),192,.00027,5,false), copper));
  }

  // Show the coil through a ghosted service cap in this mechanical preview.
  box(receiver, ferrite, [.001,WIDTH-.002,HEIGHT-.002], [RX_X+.00065,CENTER_Y,CENTER_Z]);
  box(receiver, cap, [.0008,WIDTH,HEIGHT], [RX_X-.001,CENTER_Y,CENTER_Z]);
  for (const side of [-1,1]) {
    box(receiver, caseMaterial, [.0028,.0016,HEIGHT], [RX_X,CENTER_Y+side*(WIDTH/2-.0008),CENTER_Z]);
    box(receiver, caseMaterial, [.0028,WIDTH-.0032,.0016], [RX_X,CENTER_Y,CENTER_Z+side*(HEIGHT/2-.0008)]);
  }
  winding(receiver,RX_X);

  box(dock, frame, [.102,.168,.008], [-.139,0,FLOOR_Z+.004]);
  box(dock, frame, [.014,.022,.1], [-.102,CENTER_Y,FLOOR_Z+.055]);
  box(dock, cap, [.012,WIDTH+.009,HEIGHT+.009], [TX_X-.0066,CENTER_Y,CENTER_Z]);
  box(dock, cap, [.0008,WIDTH+.003,HEIGHT+.003], [TX_X+.001,CENTER_Y,CENTER_Z]);
  winding(dock,TX_X);
  for (const side of [-1,1]) {
    box(dock, guide, [.150,.011,.013], [-.021,side*.075,FLOOR_Z+.0065]);
    box(dock, guide, [.007,.045,.011], [-.022,side*.043,FLOOR_Z+.0055]);
  }
  receiver.visible = dock.visible = false;
  return {receiver,dock};
}
