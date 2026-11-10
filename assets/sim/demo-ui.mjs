const SCENES = [
  {name:'Stand, sit, and fold', mode:'pose'},
  {name:'Step cycle', mode:'gait', ms:3500},
  {name:'Playground drop', mode:'drop', ms:3000},
  {name:'Walk, Bash, and get up', mode:'walk'},
  {name:'Beacon hunt', mode:'explore'},
  {name:'Live Duck telemetry', mode:'live', ms:4000},
];

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const active = state => ['loading', 'running', 'stopping'].includes(state);
const WALK_PUSHES = [[2, 'poke'], [4, 'nudge'], [7, 'bash']];

export class DemoCircuit {
  constructor(walk, showScene, update) {
    this.walk = walk;
    this.showScene = showScene;
    this.update = update;
    this.controller = null;
    this.runKey = null;
  }

  async visible(signal) {
    while (!signal.aborted && document.hidden) await wait(200);
    signal.throwIfAborted();
  }

  async pause(ms, signal) {
    const until = performance.now() + ms;
    while (!signal.aborted && performance.now() < until) await wait(100);
    signal.throwIfAborted();
  }

  async action(name, body) {
    const sample = await this.walk.action(name, body);
    if (!sample) throw new Error(this.walk.error || 'The UNO Q did not confirm the request.');
    return sample;
  }

  async rollout(body, signal) {
    const started = await this.action('start', body);
    this.runKey = started.run_key;
    if (!this.runKey) throw new Error('The UNO Q did not identify the demo trial.');
    const until = performance.now() + (started.duration_s + 12) * 1000;
    const pushes = body.arena ? [] : WALK_PUSHES.slice();
    while (performance.now() < until) {
      await this.visible(signal);
      const trial = this.walk.latest;
      if (trial.run_key !== started.run_key) throw new Error('A different trial took over on the UNO Q.');
      if (!active(trial.state)) {
        this.runKey = null;
        if (trial.state === 'error') throw new Error(trial.detail || 'The rollout failed.');
        if (trial.state === 'stopped') throw new Error('The rollout was stopped.');
        await this.pause(1600, signal);
        return;
      }
      const [time, kind] = pushes[0] ?? [];
      if (kind && trial.state === 'running' && trial.time_s >= time && trial.time_s < 14
          && (!trial.recovery || trial.recovery.phase === 'walk')
          && !trial.push_pending && (!trial.push || trial.push.recovery_s != null)) {
        await this.action('push', {run_id:started.run_id, kind});
        pushes.shift();
      }
      await this.pause(100, signal);
    }
    throw new Error('The rollout stopped reporting progress.');
  }

  async start() {
    if (this.controller) return;
    const controller = this.controller = new AbortController();
    const {signal} = controller;
    let message = 'Demo stopped.';
    try {
      for (let lap = 1; ; lap++) {
        for (const [index, scene] of SCENES.entries()) {
          await this.visible(signal);
          const arena = lap % 2 === 1 ? 'north' : 'south';
          const name = scene.mode === 'explore' ? `${scene.name} · ${arena} passage` : scene.name;
          this.update(name, `Lap ${lap} · ${index + 1}/${SCENES.length}`, true);
          if (scene.mode === 'pose') {
            for (const preset of ['STAND', 'SIT', 'FOLD']) {
              await this.visible(signal);
              this.showScene(scene.mode, preset);
              await this.pause(1400, signal);
            }
          } else {
            this.showScene(scene.mode, arena);
            if (scene.ms) await this.pause(scene.ms, signal);
            else await this.rollout(scene.mode === 'walk' ? {vx:0.2, yaw:0} : {arena}, signal);
          }
        }
      }
    } catch (error) {
      if (!signal.aborted) message = `Demo paused. ${error.message}`;
    } finally {
      await this.stopTrial();
      this.controller = null;
      this.update(message, 'LOOP STOPPED', false);
    }
  }

  async stopTrial() {
    if (!this.runKey) return;
    const runKey = this.runKey;
    this.runKey = null;
    try {
      await fetch('/api/lab/walk/stop', {method:'POST', keepalive:true,
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({run_key:runKey}),
        signal:AbortSignal.timeout(1800)});
    } catch { /* The worker has a bounded run time if the board is unreachable. */ }
  }

  stop() {
    this.controller?.abort();
  }

  pageHidden() {
    this.stop();
    void this.stopTrial();
  }
}
