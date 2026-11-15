import * as THREE from 'three';

// Dimensions are in metres, in the trunk frame. The outward normal is -X,
// up is +Z, and +Y is left when looking directly at the back of the Duck.
const FACE_X = -.0655;
const THROAT_X = -.063;
const BAFFLE_X = -.05945;
const BOARD_Z = -.020;
const SHELL_DEPTH = .0205;
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

function skirtGeometry(outer) {
  const inner = roundedProfile(-.0295, .0295, -.0555, .0155, .002);
  const usbMin = .0035, usbMax = .0185;
  // Break the skirt's top edge for the USB-C plug. Preserve the full face above the LEDs.
  const outline = [
    new THREE.Vector2(usbMin, .018),
    ...outer.slice(6), ...outer.slice(0, 6),
    new THREE.Vector2(usbMax, .018), new THREE.Vector2(usbMax, .0155),
    ...[...inner.slice(6), ...inner.slice(0, 6)].reverse(),
    new THREE.Vector2(usbMin, .0155),
  ];
  return new THREE.ExtrudeGeometry(new THREE.Shape(outline), {depth:SHELL_DEPTH, bevelEnabled:false})
    .applyMatrix4(PROFILE_TO_TRUNK).translate(FACE_X + .00002, 0, 0);
}

export class GuardPreview {
  constructor() {
    this.group = new THREE.Group();
    this.group.visible = false;
    this.shell = new THREE.Group();
    this.group.add(this.shell);

    const matte = color => new THREE.MeshStandardMaterial({color, roughness:.56});
    const board = matte('#126b65'), rail = matte('#579eb5'), mount = matte('#efaf51');
    const plastic = matte('#152229'), alloy = matte('#abb9c2'), contact = matte('#b5a276');
    const casing = new THREE.MeshStandardMaterial({color:'#263d4b', roughness:.66, side:THREE.DoubleSide});
    const bevel = new THREE.MeshStandardMaterial({color:'#365d6c', roughness:.67, side:THREE.DoubleSide});
    const baffle = new THREE.MeshStandardMaterial({color:'#14232b', roughness:.9, side:THREE.DoubleSide});
    const window = new THREE.MeshStandardMaterial({
      color:'#a6d8e6', roughness:.68, transparent:true, opacity:.38, depthWrite:false, side:THREE.DoubleSide,
    });

    function add(geometry, material, parent, position = [0, 0, 0]) {
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(...position);
      parent.add(mesh);
      return mesh;
    }
    const box = (material, size, position, parent = this.group) =>
      add(new THREE.BoxGeometry(...size), material, parent, position);

    box(plastic, [.011,.052,.063], [-.044,0,BOARD_Z]);
    box(board, [.0016,.0534,.0686], [-.052,0,BOARD_Z]);
    for (const side of [-1, 1]) {
      box(plastic, [.006,.0029,.050], [-.0555,side*.024,BOARD_Z]);
      for (let pin = 0; pin < 18; pin++) {
        box(contact, [.0005,.001,.001], [-.0586,side*.024,BOARD_Z + .023 - pin*.00254]);
      }
    }
    box(alloy, [.0033,.0089,.008], [-.054,.011,.0127]); // USB-C
    box(plastic, [.0015,.0065,.0005], [-.054,.011,.0168]);
    box(alloy, [.0016,.0058,.0058], [-.054,-.020,.0074]); // Power button
    box(plastic, [.001,.0027,.0027], [-.055,-.020,.0074]);
    box(alloy, [.0016,.010,.012], [-.0534,.017,-.008]);
    box(plastic, [.0022,.010,.012], [-.0538,-.006,-.015]);
    box(plastic, [.0015,.011,.010], [-.0536,-.011,-.030]);
    box(plastic, [.0013,.005,.006], [-.0535,-.010,-.044]);

    // With USB-C up, the matrix's 13 columns run down the back of the Duck.
    this.leds = new THREE.InstancedMesh(new THREE.BoxGeometry(.00075,.00125,.00125),
      new THREE.MeshBasicMaterial({color:'#ffffff'}), 13 * 8);
    const pose = new THREE.Matrix4();
    for (let col = 0; col < 13; col++) {
      for (let row = 0; row < 8; row++) {
        pose.makeTranslation(-.0533, .0057 + row * .0021, -.017 - col * .0021);
        this.leds.setMatrixAt(col * 8 + row, pose);
      }
    }
    this.group.add(this.leds);
    this.setTestPattern(false);

    const cover = roundedProfile(-.032, .032, -.058, .018, .0045);
    const outerOpening = roundedProfile(0, .0263, -.0482, -.0105, .0025);
    const throat = roundedProfile(.0015, .0248, -.0467, -.012, .0015);
    const innerOpening = roundedProfile(.0033, .0228, -.0456, -.0144, .0009);
    const baffleEdge = roundedProfile(-.0009, .028, -.0506, -.0085, .0031);
    add(plateGeometry(cover, FACE_X, outerOpening), casing, this.shell);
    add(plateGeometry(cover, THROAT_X, throat), casing, this.shell);
    add(bevelGeometry(outerOpening, throat, FACE_X, THROAT_X), bevel, this.shell);
    // A recessed baffle masks the header pins while preserving the viewing cone.
    add(bevelGeometry(throat, innerOpening, THROAT_X, BAFFLE_X), baffle, this.shell);
    add(bevelGeometry(baffleEdge, baffleEdge, THROAT_X, BAFFLE_X), baffle, this.shell);
    add(plateGeometry(baffleEdge, BAFFLE_X, innerOpening), baffle, this.shell);
    add(skirtGeometry(cover), casing, this.shell);

    // Represent the translucent co-print region. The optical finish depends on the print.
    const insert = roundedProfile(.0006, .0257, -.0476, -.0111, .0021);
    this.insert = add(plateGeometry(insert, FACE_X + .001, null), window, this.shell);

    const cap = add(new THREE.CylinderGeometry(.0025,.0025,.0012,24), rail,
      this.shell, [FACE_X - .0005,-.020,.0074]);
    cap.rotation.z = Math.PI / 2;

    const guides = [];
    for (const side of [-1, 1]) {
      const y = side * MOUNT_Y;
      const bumper = add(new THREE.CapsuleGeometry(.006,.064,6,16), rail,
        this.shell, [-.062,y,BOARD_Z]);
      bumper.rotation.x = Math.PI / 2;
      for (const z of MOUNT_Z) {
        // Proposed enclosure fasteners on the outside and mounting tabs behind them.
        const seat = add(new THREE.TorusGeometry(.0021,.00055,8,20), mount,
          this.shell, [-.0674,y,z]);
        seat.rotation.y = Math.PI / 2;
        box(plastic, [.010,.006,.007], [-.044,y,z]);
        guides.push(new THREE.Vector3(-.049,y,z), new THREE.Vector3(-.045 + EXPLODED_OFFSET,y,z));
      }
    }
    this.guides = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(guides),
      new THREE.LineDashedMaterial({color:'#efaf51',dashSize:.003,gapSize:.002}));
    this.guides.computeLineDistances();
    this.group.add(this.guides);
    this.show('cutout');
  }

  show(assembly) {
    this.insert.visible = assembly === 'translucent';
    this.shell.position.x = assembly === 'exploded' ? EXPLODED_OFFSET : 0;
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
    this.group.position.fromArray(qpos);
    this.group.quaternion.set(qpos[4],qpos[5],qpos[6],qpos[3]);
  }

  dispose() {
    const geometries = new Set(), materials = new Set();
    this.group.traverse(({geometry, material}) => {
      if (geometry) geometries.add(geometry);
      if (material) materials.add(material);
    });
    this.leds.dispose();
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
  }
}
