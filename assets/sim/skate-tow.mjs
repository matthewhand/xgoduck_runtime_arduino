const ROPE_LENGTH = .15;
const TOW_SPEED = .42;
const ACCEL_TIME = .65;
const RELEASE_N = 1.5;
const DURATION = 4;

export class SkateTow {
  constructor(mj, model, data, mount) {
    if (mount !== 'mouth' && mount !== 'chassis') throw new Error('Unknown tow mount.');
    this.body = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY.value, mount === 'mouth' ? 'jaw_soft' : 'trunk_base');
    this.site = mount === 'mouth' ? mj.mj_name2id(model, mj.mjtObj.mjOBJ_SITE.value, 'mouth_tip') : -1;
    if (this.body < 0 || (mount === 'mouth' && this.site < 0)) throw new Error('Tow mount is missing from the skate model.');
    this.data = data;
    this.point = new Float64Array(3);
    this.target = new Float64Array(3);
    this.samplePoint();
    this.target.set(this.point);
    this.target[0] += ROPE_LENGTH - .012;
    this.startX = this.target[0];
    this.startTime = data.time;
    this.previousLength = ROPE_LENGTH - .012;
    this.tension = this.peak = 0;
    this.status = 'Pulling';
  }

  samplePoint() {
    const d = this.data;
    if (this.site >= 0) this.point.set(d.site_xpos.subarray(this.site*3,this.site*3+3));
    else {
      const p = this.body*3, m = this.body*9;
      for (let i = 0; i < 3; i++) this.point[i] = d.xpos[p+i] + .044*d.xmat[m+i*3] - .049*d.xmat[m+i*3+2];
    }
  }

  step(dt) {
    if (this.status !== 'Pulling') return;
    const d = this.data, offset = this.body*6;
    d.xfrc_applied.fill(0, offset, offset+6);
    this.samplePoint();
    const t = d.time - this.startTime;
    const ramp = Math.min(t, ACCEL_TIME);
    this.target[0] = this.startX + TOW_SPEED * (ramp*ramp/(2*ACCEL_TIME) + t-ramp);
    const [x,y,z] = this.point;
    const dx = this.target[0]-x, dy = this.target[1]-y, dz = this.target[2]-z;
    const length = Math.hypot(dx,dy,dz);
    this.tension = length > ROPE_LENGTH
      ? Math.max(0, 65*(length-ROPE_LENGTH) + 1.3*(length-this.previousLength)/dt)
      : 0;
    this.previousLength = length;
    if (this.tension >= RELEASE_N || t >= DURATION) {
      this.status = this.tension >= RELEASE_N ? 'Breakaway released' : 'Pull complete';
      this.tension = 0;
      return;
    }
    this.peak = Math.max(this.peak, this.tension);
    if (!this.tension) return;
    const factor = this.tension/length;
    const fx=dx*factor, fy=dy*factor, fz=dz*factor;
    const p = this.body*3;
    const rx=x-d.xipos[p], ry=y-d.xipos[p+1], rz=z-d.xipos[p+2];
    d.xfrc_applied.set([fx,fy,fz,ry*fz-rz*fy,rz*fx-rx*fz,rx*fy-ry*fx],offset);
  }
}
