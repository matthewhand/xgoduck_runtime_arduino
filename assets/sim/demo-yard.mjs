import * as THREE from 'three';

export function createDemoYard() {
  const root = new THREE.Group();
  const box = new THREE.BoxGeometry(1, 1, 1);
  const disk = new THREE.CircleGeometry(1, 40);
  const stone = new THREE.DodecahedronGeometry(1);
  const leaf = new THREE.ConeGeometry(1, 1, 5);
  const material = color => new THREE.MeshStandardMaterial({color, roughness:.9});
  const grass = material('#314d42');
  const pond = material('#337674');
  const bank = material('#57816a');
  const paving = ['#a49b7c', '#b3a787', '#958f77'].map(material);
  const gravel = material('#75847b');
  const wood = material('#745641');
  const cap = material('#f5c579');
  const reeds = ['#7e9b5b', '#547c53', '#aab46b'].map(material);

  function place(geometry, surface, x, y, z, width, depth, height = 1) {
    const object = new THREE.Mesh(geometry, surface);
    object.position.set(x, y, z);
    object.scale.set(width, depth, height);
    root.add(object);
    return object;
  }

  place(box, grass, 1.55, .2, -.0027, 6, 4.8, .005);
  for (let i = 0; i < 23; i++) {
    const x = -.72 + i * .21;
    place(box, paving[i % paving.length], x, 0, .0001, .204, .36, .001);
    if (i % 3 === 0) {
      place(box, wood, x, .24, .065, .027, .027, .13);
      place(box, cap, x, .24, .123, .031, .031, .016);
    }
  }

  place(disk, bank, .5, .65, .0007, .91, .37);
  place(disk, pond, .5, .65, .0008, .86, .32);
  for (const [x, y, size] of [[.1,.57,.043], [.23,.62,.032], [.66,.57,.055], [.8,.64,.036], [.97,.6,.042]]) {
    place(disk, reeds[1], x, y, .001, size, size * .78);
    place(stone, cap, x + size * .2, y, .009, .010, .009, .008);
  }

  const clusters = [[-.35,.32], [-.18,.47], [.4,.34], [.92,.43], [1.4,.36], [1.8,.56],
    [2.16,.33], [2.55,.63], [3,.35], [3.45,.51], [.82,1.25], [1.63,1.35], [2.55,1.6], [1.15,1.95]];
  for (const [index, [x, y]] of clusters.entries()) {
    place(stone, gravel, x, y, .020, .052, .036, .032).rotation.z = index;
    place(stone, gravel, x + .055, y + .021, .014, .029, .026, .022);
    for (let i = 0; i < 3; i++) {
      const height = .06 + .02 * i;
      const blade = place(leaf, reeds[i], x - .035 + i * .018, y + .03, height * .42, .013, height, .01);
      blade.rotation.set(Math.PI / 2, .22 * (i - 1), 0);
    }
  }

  const shadowMap = document.createElement('canvas');
  shadowMap.width = shadowMap.height = 64;
  const context = shadowMap.getContext('2d');
  const gradient = context.createRadialGradient(32, 32, 5, 32, 32, 32);
  gradient.addColorStop(0, 'rgba(10, 18, 14, .46)');
  gradient.addColorStop(1, 'rgba(10, 18, 14, 0)');
  context.fillStyle = gradient;
  context.fillRect(0, 0, 64, 64);
  const texture = new THREE.CanvasTexture(shadowMap);
  texture.colorSpace = THREE.SRGBColorSpace;
  const shade = new THREE.MeshBasicMaterial({map:texture, transparent:true, depthWrite:false});
  const shadow = place(new THREE.PlaneGeometry(.27, .22), shade, 0, 0, .002, 1, 1);

  return {root, shadow, dispose() {
    const geometries = new Set(), materials = new Set();
    for (const object of root.children) {
      geometries.add(object.geometry);
      materials.add(object.material);
    }
    for (const geometry of geometries) geometry.dispose();
    for (const surface of materials) surface.dispose();
    texture.dispose();
  }};
}
