#!/usr/bin/env python3
"""Compute fish and water wakes on the UNO Q Adreno for active Pond Trail runs."""
import ctypes as c
import math
import os
from pathlib import Path
import sys
import time

from adreno import I, P, U, bind, compute_context, compute_program

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from pond_state import CACHE, INPUT, OUTPUT, read_sample, write_sample

FISH, COLS, ROWS = 96, 24, 16
WORDS = FISH * 4 + COLS * ROWS
PERIOD = .08
F = c.c_float
SHADER = b'''#version 310 es
precision highp float;
layout(local_size_x=64) in;
layout(std430,binding=0) buffer Pond { vec4 fish[96]; float water[384]; };
uniform vec2 duck;
uniform float phase;
void main() {
    uint i=gl_GlobalInvocationID.x;
    if(i<96u) {
        vec4 state=fish[i];
        vec2 pos=state.xy;
        float school=float(i/32u)*2.094 + phase*.52;
        float offset=float(i%32u)*2.39996;
        vec2 goal=vec2(.51*cos(school),.51*sin(school));
        goal+=.18*vec2(cos(offset+phase*.36),sin(offset+phase*.36));
        vec2 delta=(pos-duck)*vec2(.86,.32);
        float distanceToDuck=length(delta);
        float alarm=1.-smoothstep(.035,.33,distanceToDuck);
        vec2 steer=(goal-pos)*.80 + alarm*delta/max(distanceToDuck,.01)*1.65;
        vec2 velocity=mix(state.zw,steer,.13);
        vec2 next=pos+velocity*.08;
        if(length(next)>.94) {
            vec2 normal=normalize(next);
            next=normal*.94;
            velocity-=max(dot(velocity,normal),0.)*normal;
        }
        fish[i]=vec4(next,velocity);
    }
    if(i<384u) {
        vec2 p=vec2(float(i%24u)/23.,float(i/24u)/15.)*2.-1.;
        float d=length((p-duck)*vec2(.86,.32));
        float wake=sin(50.*d-9.*phase)*exp(-6.*d)*.72;
        water[i]=wake + .16*sin(12.*p.x+7.*p.y+2.6*phase) + .12*cos(6.*p.y-2.*phase);
    }
}
'''


def gpu_engine_ns():
    # EGL can share the render descriptor across several FDs. Read the first
    # matching counter for this worker rather than summing duplicate entries.
    for fd in Path('/proc/self/fdinfo').iterdir():
        try:
            for line in fd.read_text().splitlines():
                if line.startswith('drm-engine-gpu:'):
                    return int(line.split()[1])
        except (OSError, ValueError, IndexError):
            continue
    return None


def run(gl, renderer):
    program = compute_program(gl, SHADER)
    location = bind(gl, 'glGetUniformLocation', I, U, c.c_char_p)
    duck_location, phase_location = location(program, b'duck'), location(program, b'phase')
    uniform2 = bind(gl, 'glUniform2f', None, I, F, F)
    uniform1 = bind(gl, 'glUniform1f', None, I, F)
    buffer = U()
    bind(gl, 'glGenBuffers', None, I, P)(1, c.byref(buffer))
    bind(gl, 'glBindBuffer', None, U, U)(0x90D2, buffer.value)
    bind(gl, 'glBindBufferBase', None, U, U, U)(0x90D2, 0, buffer.value)
    allocate = bind(gl, 'glBufferData', None, U, c.c_ssize_t, P, U)
    dispatch = bind(gl, 'glDispatchCompute', None, U, U, U)
    barrier = bind(gl, 'glMemoryBarrier', None, U)
    map_buffer = bind(gl, 'glMapBufferRange', P, U, c.c_ssize_t, c.c_ssize_t, U)
    unmap = bind(gl, 'glUnmapBuffer', U, U)
    error = bind(gl, 'glGetError', U)
    state = (F * WORDS)()
    for i in range(FISH):
        angle = i * 2.399963
        radius = .80 * math.sqrt((i + .5) / FISH)
        state[i*4], state[i*4+1] = radius * math.cos(angle), radius * math.sin(angle)
    run_key, frame = None, 0
    counter, gpu_load, counter_at = None, None, 0
    while True:
        demand = read_sample(INPUT)
        if not demand:
            time.sleep(.20)
            continue
        began = time.monotonic()
        if demand['run_key'] != run_key:
            run_key, frame = demand['run_key'], 0
            counter, gpu_load, counter_at = None, None, 0
            allocate(0x90D2, c.sizeof(state), state, 0x88E8)
        x, y = demand['xy']
        uniform2(duck_location, (x - .5) / .86, (y - .65) / .32)
        uniform1(phase_location, frame * PERIOD)
        dispatch((COLS * ROWS) // 64, 1, 1)
        barrier(0x2200)  # SSBO visibility for the next dispatch and CPU readback.
        pointer = map_buffer(0x90D2, 0, c.sizeof(state), 1)
        if not pointer or error():
            raise RuntimeError('Pond compute or readback failed')
        values = c.cast(pointer, c.POINTER(F))[:WORDS]
        if not unmap(0x90D2):
            raise RuntimeError('Pond compute buffer contents were lost')
        elapsed = (time.monotonic() - began) * 1000
        if began - counter_at >= 1:
            current = gpu_engine_ns()
            if current is not None and counter is not None:
                gpu_load = round(max(0., current - counter) / (began - counter_at) / 1e7, 3)
            counter, counter_at = current, began
        fish = []
        for i in range(FISH):
            x, y, vx, vy = values[i*4:i*4+4]
            fish.extend((round(x*1000), round(y*1000), round(100*math.atan2(vy*.32, vx*.86))))
        water = [round(value*100) for value in values[FISH*4:]]
        frame += 1
        write_sample(OUTPUT, dict(run_key=run_key, frame=frame, renderer=renderer,
                                 compute_ms=round(elapsed, 2), gpu_load_percent=gpu_load,
                                 fish=fish, water=water))
        time.sleep(max(0, PERIOD - (time.monotonic() - began)))


def main():
    os.nice(10)
    CACHE.mkdir(exist_ok=True)
    while read_sample(INPUT) is None:
        time.sleep(.20)
    with compute_context() as (gl, renderer, _):
        print(f'Pond compute on {renderer}', flush=True)
        run(gl, renderer)


if __name__ == '__main__':
    main()
