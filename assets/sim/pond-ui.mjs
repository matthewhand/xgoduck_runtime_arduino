import * as THREE from 'three';

const FISH = 96, COLS = 24, ROWS = 16;
const lerp = THREE.MathUtils.lerp;

export class PondLife {
  constructor(parent, status) {
    this.status = status;
    this.group = new THREE.Group();
    this.group.visible = false;
    parent.add(this.group);

    const shape = new THREE.Shape();
    shape.moveTo(.022, 0);
    shape.quadraticCurveTo(.004, .014, -.013, .002);
    shape.lineTo(-.023, .009);
    shape.lineTo(-.020, 0);
    shape.lineTo(-.023, -.009);
    shape.lineTo(-.013, -.002);
    shape.quadraticCurveTo(.004, -.014, .022, 0);
    this.fish = new THREE.InstancedMesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial(), FISH);
    this.fish.frustumCulled = false;
    const colors = ['#bceee8', '#dff5cc', '#75c8bb', '#ffd88f'];
    for (let i = 0; i < FISH; i++) this.fish.setColorAt(i, new THREE.Color(colors[i % colors.length]));
    this.transform = new THREE.Object3D();
    this.group.add(this.fish);

    const water = new THREE.PlaneGeometry(1.72, .64, COLS - 1, ROWS - 1);
    this.vertices = water.attributes.position;
    const index = water.index.array;
    const inside = i => Math.hypot(this.vertices.getX(i)/.86, this.vertices.getY(i)/.32) <= .98;
    const triangles = [];
    for (let i = 0; i < index.length; i += 3) {
      const triangle = [index[i], index[i + 1], index[i + 2]];
      if (triangle.every(inside)) triangles.push(...triangle);
    }
    water.setIndex(triangles);
    this.colors = new THREE.Float32BufferAttribute(new Float32Array(COLS * ROWS * 3), 3);
    water.setAttribute('color', this.colors);
    this.water = new THREE.Mesh(water, new THREE.MeshBasicMaterial({vertexColors:true}));
    this.water.position.set(.5, .65, .007);
    this.group.add(this.water);
    this.baseColor = new THREE.Color('#3b817e');
  }

  async request(runKey) {
    this.pending = true;
    try {
      const response = await fetch('/api/lab/pond', {cache:'no-store', signal:AbortSignal.timeout(1500)});
      if (!response.ok) return;
      const frame = await response.json();
      if (this.runKey !== runKey || !frame.available || frame.run_key !== runKey
          || frame.fish?.length !== FISH * 3 || frame.water?.length !== COLS * ROWS
          || !frame.fish.every(Number.isFinite) || !frame.water.every(Number.isFinite)) return;
      if (this.next?.frame === frame.frame) return;
      this.previous = this.next ?? frame;
      this.next = frame;
      this.arrived = performance.now();
    } catch { /* Hide stale results when the host worker is unreachable. */ }
    finally { this.pending = false; }
  }

  update(runKey, now) {
    if (this.runKey !== runKey) {
      if (!runKey && this.runKey) this.status.textContent = 'Pond worker idle.';
      this.runKey = runKey;
      this.next = this.previous = null;
      this.nextPoll = 0;
    }
    if (runKey && !this.pending && now >= this.nextPoll) {
      this.nextPoll = now + 125;
      void this.request(runKey);
    }
    const visible = Boolean(this.next && now - this.arrived < 1500);
    this.group.visible = visible;
    if (runKey) {
      const load = this.next?.gpu_load_percent;
      const activity = Number.isFinite(load) ? ` · ${load.toFixed(3)}% GPU busy` : '';
      const text = visible ? `${this.next.renderer} · ${FISH} fish${activity}` : 'Waiting for the UNO Q pond worker…';
      if (this.status.textContent !== text) this.status.textContent = text;
    }
    if (!visible) return;
    const blend = Math.min(1, Math.max(0, (now - this.arrived) / 125));
    for (let i = 0; i < FISH; i++) {
      const j = i * 3, a = this.previous.fish, b = this.next.fish;
      this.transform.position.set(.5 + .00086 * lerp(a[j], b[j], blend), .65 + .00032 * lerp(a[j+1], b[j+1], blend), .015);
      const turn = (b[j+2] - a[j+2]) / 100;
      this.transform.rotation.z = a[j+2] / 100 + Math.atan2(Math.sin(turn), Math.cos(turn)) * blend;
      this.transform.updateMatrix();
      this.fish.setMatrixAt(i, this.transform.matrix);
    }
    this.fish.instanceMatrix.needsUpdate = true;
    for (let row = 0; row < ROWS; row++) for (let col = 0; col < COLS; col++) {
      const i = row * COLS + col, source = (ROWS - 1 - row) * COLS + col;
      const ripple = lerp(this.previous.water[source], this.next.water[source], blend) / 100;
      const light = 1 + .47 * ripple;
      this.vertices.setZ(i, .006 * ripple);
      this.colors.setXYZ(i, this.baseColor.r * light, this.baseColor.g * light, this.baseColor.b * light);
    }
    this.vertices.needsUpdate = this.colors.needsUpdate = true;
  }

  dispose() {
    for (const mesh of [this.fish, this.water]) {
      mesh.geometry.dispose();
      mesh.material.dispose();
    }
    this.fish.dispose();
  }
}
