#!/usr/bin/env python3
"""Headless Adreno compute proof using installed EGL/GLES and Python's ctypes.

No compiler, pip packages, browser or network connection is required.
"""
import argparse
import ctypes as c
import json
import os
import time

N = 65536
ROUNDS = 128
U, I, P = c.c_uint, c.c_int, c.c_void_p


def bind(lib, name, result, *arguments):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, arguments
    return fn


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
    egl, gl = c.CDLL('libEGL.so.1'), c.CDLL('libGLESv2.so.2')
    display = bind(egl, 'eglGetPlatformDisplay', P, U, P, P)(0x31DD, None, None)
    if not display or not bind(egl, 'eglInitialize', U, P, P, P)(display, None, None):
        raise RuntimeError('Surfaceless EGL is unavailable')
    context, surface = None, None
    try:
        if not bind(egl, 'eglBindAPI', U, U)(0x30A0):
            raise RuntimeError('Cannot select OpenGL ES')
        config, count = P(), I()
        attributes = (I * 5)(0x3033, 1, 0x3040, 0x40, 0x3038)
        if not bind(egl, 'eglChooseConfig', U, P, P, P, I, P)(display, attributes, c.byref(config), 1, c.byref(count)) or not count.value:
            raise RuntimeError('No OpenGL ES 3 configuration')
        surface = bind(egl, 'eglCreatePbufferSurface', P, P, P, P)(display, config, (I * 5)(0x3057, 1, 0x3056, 1, 0x3038))
        context = bind(egl, 'eglCreateContext', P, P, P, P, P)(display, config, None, (I * 5)(0x3098, 3, 0x30FB, 1, 0x3038))
        if not context or not surface or not bind(egl, 'eglMakeCurrent', U, P, P, P, P)(display, surface, surface, context):
            raise RuntimeError('Cannot create an OpenGL ES 3.1 context')
        string = bind(gl, 'glGetString', c.c_char_p, U)
        renderer = (string(0x1F01) or b'unknown').decode()
        version = (string(0x1F02) or b'unknown').decode()
        print(json.dumps(dict(renderer=renderer, version=version)), flush=True)
        if not ('Adreno' in renderer or 'FD702' in renderer):
            raise RuntimeError('Expected Adreno hardware; software rendering is not accepted')
        shader = bind(gl, 'glCreateShader', U, U)(0x91B9)
        source = c.c_char_p(b'''#version 310 es
layout(local_size_x=64) in;
layout(std430,binding=0) buffer Output { uint values[]; };
void main() { uint x=gl_GlobalInvocationID.x; uint v=x;
for(uint i=0u;i<128u;++i) { v^=v>>13u; v=v*1664525u+1013904223u; v^=v<<7u; }
values[x]=v; }
''')
        bind(gl, 'glShaderSource', None, U, I, P, P)(shader, 1, c.byref(source), None)
        bind(gl, 'glCompileShader', None, U)(shader)
        okay = I()
        bind(gl, 'glGetShaderiv', None, U, U, P)(shader, 0x8B81, c.byref(okay))
        if not okay.value:
            log = c.create_string_buffer(4096)
            bind(gl, 'glGetShaderInfoLog', None, U, I, P, P)(shader, len(log), None, log)
            raise RuntimeError(log.value.decode())
        program = bind(gl, 'glCreateProgram', U)()
        bind(gl, 'glAttachShader', None, U, U)(program, shader)
        bind(gl, 'glLinkProgram', None, U)(program)
        bind(gl, 'glGetProgramiv', None, U, U, P)(program, 0x8B82, c.byref(okay))
        if not okay.value:
            raise RuntimeError('Compute program link failed')
        bind(gl, 'glUseProgram', None, U)(program)
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
    finally:
        bind(egl, 'eglMakeCurrent', U, P, P, P, P)(display, None, None, None)
        if context:
            bind(egl, 'eglDestroyContext', U, P, P)(display, context)
        if surface:
            bind(egl, 'eglDestroySurface', U, P, P)(display, surface)
        bind(egl, 'eglTerminate', U, P)(display)


if __name__ == '__main__':
    main()
