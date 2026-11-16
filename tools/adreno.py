"""Headless GLES 3.1 compute on the UNO Q host."""
from contextlib import contextmanager
import ctypes as c

U, I, P = c.c_uint, c.c_int, c.c_void_p


def bind(lib, name, result, *arguments):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, arguments
    return fn


@contextmanager
def compute_context():
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
        if 'Adreno' not in renderer and 'FD702' not in renderer:
            raise RuntimeError(f'Expected Adreno hardware, got {renderer}')
        yield gl, renderer, version
    finally:
        bind(egl, 'eglMakeCurrent', U, P, P, P, P)(display, None, None, None)
        if context:
            bind(egl, 'eglDestroyContext', U, P, P)(display, context)
        if surface:
            bind(egl, 'eglDestroySurface', U, P, P)(display, surface)
        bind(egl, 'eglTerminate', U, P)(display)


def compute_program(gl, source):
    shader = bind(gl, 'glCreateShader', U, U)(0x91B9)
    text = c.c_char_p(source)
    bind(gl, 'glShaderSource', None, U, I, P, P)(shader, 1, c.byref(text), None)
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
    bind(gl, 'glDeleteShader', None, U)(shader)
    bind(gl, 'glGetProgramiv', None, U, U, P)(program, 0x8B82, c.byref(okay))
    if not okay.value:
        log = c.create_string_buffer(4096)
        bind(gl, 'glGetProgramInfoLog', None, U, I, P, P)(program, len(log), None, log)
        raise RuntimeError(log.value.decode())
    bind(gl, 'glUseProgram', None, U)(program)
    return program
