import * as THREE from 'three';
import {buildDockPreview} from './dock-preview.mjs?v=7';

// Dimensions are in metres, in the trunk frame. The outward normal is -X,
// up is +Z, and +Y is left when looking directly at the back of the Duck.
const FACE_X = -.078;
const THROAT_X = FACE_X + .0025;
const CARRIER_X = -.0625;
const BOARD_Z = -.020;
const EXPLODED_OFFSET = -.052;
const MOUNT_Y = .033;
const MOUNT_Z = [-.044, .005];
const PROFILE_TO_TRUNK = new THREE.Matrix4().makeBasis(
  new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(1, 0, 0),
);
const HEART = [
  '........', '........', '..#..#..', '.######.', '.######.',
  '.######.', '..####..', '...##...', '...##...', '........',
  '........', '........', '........',
];

function roundedProfile(minY, maxY, minZ, maxZ, radius) {
  const centers = [
    [maxY - radius, maxZ - radius], [minY + radius, maxZ - radius],
    [minY + radius, minZ + radius], [maxY - radius, minZ + radius],
  ];
  return centers.flatMap(([y, z], corner) => Array.from({length: 6}, (_, step) => {
    const angle = (corner + step / 5) * Math.PI / 2;
    return new THREE.Vector2(y + radius * Math.cos(angle), z + radius * Math.sin(angle));
  }));
}

function plateGeometry(outline, x, aperture) {
  const shape = new THREE.Shape(outline);
  if (aperture) shape.holes.push(new THREE.Path(aperture));
  return new THREE.ShapeGeometry(shape).applyMatrix4(PROFILE_TO_TRUNK).translate(x, 0, 0);
}

function solidPlate(outline, x, thickness, aperture) {
  const shape = new THREE.Shape(outline);
  if (aperture) shape.holes.push(new THREE.Path(aperture));
  return new THREE.ExtrudeGeometry(shape, {depth:thickness, bevelEnabled:false})
    .applyMatrix4(PROFILE_TO_TRUNK).translate(x, 0, 0);
}

function bevelGeometry(outer, throat, outerX, throatX) {
  const positions = [], faces = [];
  for (let i = 0; i < outer.length; i++) {
    const next = (i + 1) % outer.length;
    const index = positions.length / 3;
    positions.push(outerX, outer[i].x, outer[i].y, outerX, outer[next].x, outer[next].y,
      throatX, throat[next].x, throat[next].y, throatX, throat[i].x, throat[i].y);
    faces.push(index, index + 1, index + 2, index, index + 2, index + 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(faces);
  geometry.computeVertexNormals();
  return geometry;
}

function cushionedSkidGeometry() {
  const geometry = new THREE.CapsuleGeometry(.004, .064, 6, 16).rotateX(Math.PI / 2);
  const faces = geometry.index.array;
  const positions = geometry.attributes.position;
  const skid = [], cushion = [];
  for (let index = 0; index < faces.length; index += 3) {
    const a = faces[index], b = faces[index + 1], c = faces[index + 2];
    const outerFace = positions.getX(a) + positions.getX(b) + positions.getX(c) < 0;
    (outerFace ? skid : cushion).push(a, b, c);
  }
  geometry.setIndex([...skid, ...cushion]);
  geometry.addGroup(0, skid.length, 0);
  geometry.addGroup(skid.length, cushion.length, 1);
  return geometry;
}

export class GuardPreview {
  constructor() {
    this.group = new THREE.Group();
    this.group.visible = false;
    this.robot = new THREE.Group();
    this.shell = new THREE.Group();
    this.carrier = new THREE.Group();
    const {receiver, dock, setDesign} = buildDockPreview();
    this.receiver = receiver;
    this.dock = dock;
    this.shell.add(receiver);
    this.setDockDesign = setDesign;
    this.robot.add(this.shell, this.carrier);
    this.group.add(this.robot, dock);

    const matte = color => new THREE.MeshStandardMaterial({color, roughness:.56});
    const board = matte('#126b65'), carrier = matte('#254d9a'), rail = matte('#579eb5');
    const mount = matte('#efaf51'), connector = matte('#e7e5d7');
    const cushion = matte('#d47c47');
    const plastic = matte('#152229'), alloy = matte('#abb9c2'), contact = matte('#b5a276');
    const casing = new THREE.MeshStandardMaterial({color:'#263d4b', roughness:.66, side:THREE.DoubleSide});
    const bevel = new THREE.MeshStandardMaterial({color:'#365d6c', roughness:.67, side:THREE.DoubleSide});
    const window = new THREE.MeshStandardMaterial({
      color:'#a6d8e6', roughness:.65, transparent:true, opacity:.32, depthWrite:false,
    });

    function add(geometry, material, parent, position = [0, 0, 0]) {
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(...position);
      parent.add(mesh);
      return mesh;
    }
    const box = (material, size, position, parent = this.robot) =>
      add(new THREE.BoxGeometry(...size), material, parent, position);

    box(plastic, [.011,.052,.063], [-.044,0,BOARD_Z]);
    box(board, [.0016,.0534,.0686], [-.052,0,BOARD_Z]);
    // Luwu's carrier plugs into the UNO Q headers. Its own cut-out lets
    // the display face the viewer. The STEP opening is 27.94 × 16.764 mm.
    const pcb = roundedProfile(-.02667,.02667,-.05429,.01429,.0015);
    const carrierOpening = roundedProfile(.005944,.022708,-.04425,-.01631,.0003);
    add(solidPlate(pcb, CARRIER_X, .00162, carrierOpening), carrier, this.carrier);
    for (const {y, z, count} of [
      {y:-.024, z:.0118, count:18}, {y:.024, z:.0015, count:14},
    ]) {
      box(plastic, [.0064,.0029,count*.00254], [-.056,y,z-(count-1)*.00127]);
      for (let pin = 0; pin < count; pin++) {
        box(contact, [.0045,.001,.001], [CARRIER_X+.0013,y,z-pin*.00254], this.carrier);
      }
    }
    box(alloy, [.0033,.0089,.008], [-.054,.011,.0127]); // USB-C
    box(plastic, [.0015,.0065,.0005], [-.054,.011,.0168]);
    box(alloy, [.0016,.0058,.0058], [-.054,-.020,.0074]); // Power button
    box(connector, [.001,.0027,.0027], [-.055,-.020,.0074]);
    box(alloy, [.0016,.010,.012], [-.0534,.017,-.008]);
    box(plastic, [.0022,.010,.012], [-.0538,-.006,-.015]);
    box(plastic, [.0015,.011,.010], [-.0536,-.011,-.030]);
    box(plastic, [.0013,.005,.006], [-.0535,-.010,-.044]);
    // Schematic carrier parts. The top edge is left open for the actual plugs.
    box(alloy, [.009,.010,.012], [-.0669,.018,.008], this.carrier); // charge jack
    box(plastic, [.007,.009,.002], [-.067,.018,.014], this.carrier);
    box(alloy, [.006,.009,.007], [-.065,-.019,.005], this.carrier); // battery switch
    box(plastic, [.003,.005,.003], [-.067,-.019,.009], this.carrier);
    for (const y of [-.007,.001,.009]) {
      box(connector, [.005,.006,.0043], [-.0649,y,.012], this.carrier);
      const capacitor = add(new THREE.CylinderGeometry(.0027,.0027,.0065,16),
        alloy,this.carrier,[-.0657,y,.0045]);
      capacitor.rotation.z = Math.PI / 2;
    }
    box(connector, [.004,.007,.003], [-.0601,.016,-.055]); // bottom-edge access

    // With USB-C up, the matrix's 13 columns run down the back of the Duck.
    this.leds = new THREE.InstancedMesh(new THREE.BoxGeometry(.00075,.00125,.00125),
      new THREE.MeshBasicMaterial({color:'#ffffff'}), 13 * 8);
    const pose = new THREE.Matrix4();
    for (let col = 0; col < 13; col++) {
      for (let row = 0; row < 8; row++) {
        pose.makeTranslation(-.0533, .007326 + row * .002, -.01768 - col * .0021);
        this.leds.setMatrixAt(col * 8 + row, pose);
      }
    }
    this.robot.add(this.leds);
    this.setTestPattern(false);

    // A standoff faceplate, open between four mounting posts on every edge.
    const cover = roundedProfile(-.034, .034, -.058, .018, .005);
    const outerOpening = roundedProfile(.0005, .028, -.050, -.0105, .0025);
    const throat = roundedProfile(.002, .0265, -.0485, -.012, .0015);
    add(plateGeometry(cover, FACE_X, outerOpening), casing, this.shell);
    add(plateGeometry(cover, THROAT_X, throat), casing, this.shell);
    add(bevelGeometry(cover, cover, FACE_X, THROAT_X), casing, this.shell);
    add(bevelGeometry(outerOpening, throat, FACE_X, THROAT_X), bevel, this.shell);
    // The insert overlaps the aperture wall so the shell supports it all around.
    const insert = roundedProfile(.0012, .0273, -.0493, -.0112, .0021);
    this.insert = add(solidPlate(insert, FACE_X + .0018, .0014), window, this.shell);

    const guides = [];
    const skidGeometry = cushionedSkidGeometry();
    for (const side of [-1, 1]) {
      const y = side * MOUNT_Y;
      add(skidGeometry, [rail, cushion], this.shell, [FACE_X,y,BOARD_Z]);
      for (const z of MOUNT_Z) {
        // Proposed enclosure fasteners on the outside and mounting tabs behind them.
        const post = add(new THREE.CylinderGeometry(.003,.003,.028,16), casing,
          this.shell, [FACE_X+.014,y,z]);
        post.rotation.z = Math.PI / 2;
        const rim = add(new THREE.TorusGeometry(.0017,.00045,8,20), mount,
          this.shell, [FACE_X-.0034,y,z]);
        rim.rotation.y = Math.PI / 2;
        box(plastic, [.010,.006,.007], [-.044,y,z]);
        guides.push(new THREE.Vector3(-.049,y,z), new THREE.Vector3(-.045 + EXPLODED_OFFSET,y,z));
      }
    }
    this.guides = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(guides),
      new THREE.LineDashedMaterial({color:'#efaf51',dashSize:.003,gapSize:.002}));
    this.guides.computeLineDistances();
    this.robot.add(this.guides);
    this.show('translucent');
  }

  show(assembly) {
    const docking = assembly === 'dock';
    this.insert.visible = assembly === 'translucent' || docking;
    this.receiver.visible = this.dock.visible = docking;
    this.shell.position.x = assembly === 'exploded' ? EXPLODED_OFFSET : 0;
    this.carrier.position.x = assembly === 'exploded' ? -.028 : 0;
    this.guides.visible = assembly === 'exploded';
  }

  setTestPattern(allOn) {
    const lit = new THREE.Color('#6fc4ff'), dim = new THREE.Color('#224f85');
    let index = 0;
    for (const row of HEART) {
      for (const pixel of row) this.leds.setColorAt(index++, allOn || pixel === '#' ? lit : dim);
    }
    this.leds.instanceColor.needsUpdate = true;
  }

  followTrunk(qpos) {
    this.robot.position.fromArray(qpos);
    this.robot.quaternion.set(qpos[4],qpos[5],qpos[6],qpos[3]);
  }

  dispose() {
    const geometries = new Set(), materials = new Set();
    this.group.traverse(({geometry, material}) => {
      if (geometry) geometries.add(geometry);
      if (Array.isArray(material)) material.forEach(item => materials.add(item));
      else if (material) materials.add(material);
    });
    this.leds.dispose();
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
  }
}
