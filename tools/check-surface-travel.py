"""Screen forward locomotion and stopping with the shipped foot and roller policies."""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
import mujoco as mj
from walk_sim import WalkSimulation, WHEEL_NAMES, SLOT_S, SUBSTEPS
from skate_dock_exit import load_roller_policy, roller_target


def run(surface, slope_deg, cross_deg, skates, heading):
    def ground(spec):
        # A positive fore-aft grade raises the floor in the direction of travel.
        floor = spec.geom('floor')
        pitch, roll = map(lambda deg: math.radians(deg)/2, (-slope_deg, cross_deg))
        floor.quat = [math.cos(roll)*math.cos(pitch), math.sin(roll)*math.cos(pitch),
                      math.cos(roll)*math.sin(pitch), -math.sin(roll)*math.sin(pitch)]
        if surface.startswith('Tile'):
            width = .45 if surface == 'Tile 450' else .60
            floor.pos = [0,0,-.003]
            for row in range(-2,3):
                for col in range(-2,6):
                    name = f'tile_{row}_{col}'
                    spec.worldbody.add_geom(name=name, type=mj.mjtGeom.mjGEOM_BOX,
                        size=[(width-.005)/2,(width-.005)/2,.0015],
                        pos=[.12+(col+.5)*width,row*width,-.0015], contype=1, conaffinity=1)
    sim = WalkSimulation(.16, 0, configure=ground, skates=skates)
    m,d = sim.model,sim.data
    grip = .55 if surface=='Smooth' else 1.1 if surface=='Carpet' else .85
    m.geom_friction[[sim.floor,*sim.feet],0] = grip
    if skates:
        mj.mj_resetDataKeyframe(m,d,m.key('home').id)
        if surface == 'Carpet':
            for wheel in WHEEL_NAMES:
                m.dof_damping[m.joint(wheel).dofadr[0]] = .0015
        roller = load_roller_policy()
    support = [sim.floor,*[i for i in range(m.ngeom) if (m.geom(i).name or '').startswith('tile_')]]
    for geom in support:
        m.geom_friction[geom,0] = grip
        if surface == 'Carpet':
            m.geom_solref[geom,:] = [.04,1]
            m.geom_priority[geom] = 2
    angle = math.radians(heading)/2
    d.qpos[sim.root+3:sim.root+7] = [math.cos(angle),0,0,math.sin(angle)]
    mj.mj_forward(m,d)
    fall = None
    at_stop = None
    max_side = 0.
    drive_slots = round(6/SLOT_S)
    for tick in range(drive_slots+round(1/SLOT_S)):
        speed = .16 if tick < drive_slots else 0.
        if skates:
            d.ctrl[sim.actuators] = roller_target(sim,roller,[speed,0,0])
            mj.mj_step(m,d,nstep=SUBSTEPS)
        else:
            sim.command = (speed,0,0)
            sim.tick()
        x,y,z,w,qx,qy,qz = d.qpos[sim.root:sim.root+7]
        max_side = max(max_side,abs(float(y)))
        ground_z = x*math.tan(math.radians(slope_deg)) + y*math.tan(math.radians(cross_deg))
        if 1-2*(qx*qx+qy*qy)<.70 or z-ground_z<.085:
            fall = round(float(d.time),2)
            break
        if tick+1 == drive_slots:
            at_stop = (float(x),float(y))
    distance = None if at_stop is None else round(at_stop[0],3)
    return dict(heading_deg=heading, fall_s=fall, forward_m=distance, max_side_m=round(max_side,3),
                travelled_after_stop_m=None if at_stop is None or fall else round(math.dist(at_stop,(x,y)),3),
                tracked=bool(fall is None and .30 <= distance <= 1.50 and max_side<=.15))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    args=parser.parse_args()
    results={}
    for surface in ('Smooth','Carpet','Tile 450','Tile 600'):
        slopes = [(0,0),(3,0),(-3,0),(0,3)] if surface=='Smooth' else [(0,0)]
        for slope,cross in slopes:
            for skates in (False,True):
                key=f'{surface} / grade {slope} / cross {cross} / {"skates" if skates else "feet"}'
                rows=[run(surface,slope,cross,skates,h) for h in (-4,-2,0,2,4)]
                results[key]=rows
                print(key,sum(r['tracked'] for r in rows),'of',len(rows),flush=True)
    args.results.write_text(json.dumps(results,indent=2)+'\n',encoding='utf8')
