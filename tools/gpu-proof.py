#!/usr/bin/env python3
"""Headless Adreno compute proof using installed EGL/GLES and Python's ctypes.

No compiler, pip packages, browser or network connection is required.
"""
import argparse
import ctypes as c
import json
import os
import time

from adreno import I, P, U, bind, compute_context, compute_program

N = 65536
ROUNDS = 128


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30:
        parser.error('--seconds must be 1..30')
    # The proof and its CPU reference are background diagnostics, below the
    # robot's control processes in the Linux scheduler.
    if hasattr(os, 'nice'):
        os.nice(10)
    with compute_context() as (gl, renderer, version):
        print(json.dumps(dict(renderer=renderer, version=version)), flush=True)
        source = b'''#version 310 es
layout(local_size_x=64) in;
layout(std430,binding=0) buffer Output { uint values[]; };
void main() { uint x=gl_GlobalInvocationID.x; uint v=x;
for(uint i=0u;i<128u;++i) { v^=v>>13u; v=v*1664525u+1013904223u; v^=v<<7u; }
values[x]=v; }
'''
        compute_program(gl, source)
        buffer = U()
        bind(gl, 'glGenBuffers', None, I, P)(1, c.byref(buffer))
        bind(gl, 'glBindBuffer', None, U, U)(0x90D2, buffer.value)
        bind(gl, 'glBufferData', None, U, c.c_ssize_t, P, U)(0x90D2, N * 4, None, 0x88E9)
        bind(gl, 'glBindBufferBase', None, U, U, U)(0x90D2, 0, buffer.value)
        dispatch = bind(gl, 'glDispatchCompute', None, U, U, U)
        barrier = bind(gl, 'glMemoryBarrier', None, U)
        finish = bind(gl, 'glFinish', None)
        error = bind(gl, 'glGetError', U)
        if error():
            raise RuntimeError('GPU buffer setup failed')
        begin, batches = time.monotonic(), 0
        while time.monotonic() - begin < args.seconds:
            dispatch(N // 64, 1, 1)
            barrier(0x200)
            finish()
            if error():
                raise RuntimeError('GPU compute dispatch failed')
            batches += 1
            time.sleep(.02)
        pointer = bind(gl, 'glMapBufferRange', P, U, c.c_ssize_t, c.c_ssize_t, U)(0x90D2, 0, N * 4, 1)
        if not pointer:
            raise RuntimeError('GPU result readback failed')
        values = c.cast(pointer, c.POINTER(c.c_uint32))
        for index in range(N):
            expected = index
            for _ in range(ROUNDS):
                expected ^= expected >> 13
                expected = (expected * 1664525 + 1013904223) & 0xffffffff
                expected ^= (expected << 7) & 0xffffffff
            if values[index] != expected:
                raise RuntimeError(f'GPU result mismatch at {index}')
        bind(gl, 'glUnmapBuffer', U, U)(0x90D2)
        print(json.dumps(dict(result='PASS', batches=batches, verified_results=N,
                              elapsed_s=round(time.monotonic() - begin, 2))), flush=True)


if __name__ == '__main__':
    main()
