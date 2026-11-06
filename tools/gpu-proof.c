/* Bounded, headless OpenGL ES 3.1 compute proof for the UNO Q Adreno GPU.
 * Build on Linux: cc -O2 tools/gpu-proof.c -o .cache/gpu-proof -lEGL -lGLESv2
 * Run: .cache/gpu-proof [seconds:1..30]
 */
#define _POSIX_C_SOURCE 200809L
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl31.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define ELEMENTS 65536u
#define ROUNDS 128u

static void fail(const char *message) {
  fprintf(stderr, "GPU proof failed: %s\n", message);
  exit(1);
}

static double seconds_now(void) {
  struct timespec now;
  clock_gettime(CLOCK_MONOTONIC, &now);
  return now.tv_sec + now.tv_nsec / 1e9;
}

static uint32_t expected(uint32_t value) {
  for (unsigned i = 0; i < ROUNDS; ++i) {
    value ^= value >> 13;
    value = value * 1664525u + 1013904223u;
    value ^= value << 7;
  }
  return value;
}

int main(int argc, char **argv) {
  unsigned duration = 10;
  if (argc > 2) fail("usage: gpu-proof [seconds:1..30]");
  if (argc == 2) {
    char *end;
    unsigned long value = strtoul(argv[1], &end, 10);
    if (!*argv[1] || *end || value < 1 || value > 30) fail("duration must be 1..30 seconds");
    duration = (unsigned)value;
  }
  EGLDisplay display = eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
  if (display == EGL_NO_DISPLAY || !eglInitialize(display, NULL, NULL)) fail("surfaceless EGL unavailable");
  if (!eglBindAPI(EGL_OPENGL_ES_API)) fail("cannot select OpenGL ES");
  const EGLint config_attrs[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
    EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_NONE};
  EGLConfig config;
  EGLint count;
  if (!eglChooseConfig(display, config_attrs, &config, 1, &count) || !count) fail("no ES3 EGL configuration");
  const EGLint surface_attrs[] = {EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE};
  EGLSurface surface = eglCreatePbufferSurface(display, config, surface_attrs);
  const EGLint context_attrs[] = {EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 1, EGL_NONE};
  EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attrs);
  if (context == EGL_NO_CONTEXT || surface == EGL_NO_SURFACE ||
      !eglMakeCurrent(display, surface, surface, context)) fail("cannot create ES 3.1 context");
  const char *renderer = (const char *)glGetString(GL_RENDERER);
  const char *version = (const char *)glGetString(GL_VERSION);
  printf("Renderer: %s\nOpenGL ES: %s\n", renderer ? renderer : "unknown", version ? version : "unknown");
  fflush(stdout);
  if (!renderer || !(strstr(renderer, "Adreno") || strstr(renderer, "FD702")))
    fail("expected Adreno hardware; software rendering or another GPU is not accepted");
  const char *source =
    "#version 310 es\n"
    "layout(local_size_x=64) in;\n"
    "layout(std430,binding=0) buffer Output { uint values[]; };\n"
    "void main() { uint x=gl_GlobalInvocationID.x; uint v=x;\n"
    "for(uint i=0u;i<128u;++i) { v^=v>>13u; v=v*1664525u+1013904223u; v^=v<<7u; }\n"
    "values[x]=v; }\n";
  GLuint shader = glCreateShader(GL_COMPUTE_SHADER);
  glShaderSource(shader, 1, &source, NULL);
  glCompileShader(shader);
  GLint okay;
  glGetShaderiv(shader, GL_COMPILE_STATUS, &okay);
  if (!okay) {
    char log[2048]; glGetShaderInfoLog(shader, sizeof(log), NULL, log);
    fprintf(stderr, "%s\n", log); fail("compute shader compilation");
  }
  GLuint program = glCreateProgram();
  glAttachShader(program, shader);
  glLinkProgram(program);
  glGetProgramiv(program, GL_LINK_STATUS, &okay);
  if (!okay) fail("compute shader link");
  glUseProgram(program);
  GLuint buffer;
  glGenBuffers(1, &buffer);
  glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer);
  glBufferData(GL_SHADER_STORAGE_BUFFER, ELEMENTS * sizeof(uint32_t), NULL, GL_DYNAMIC_READ);
  glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, buffer);
  if (glGetError() != GL_NO_ERROR) fail("GPU buffer setup");
  unsigned batches = 0;
  const double begin = seconds_now();
  do {
    glDispatchCompute(ELEMENTS / 64, 1, 1);
    glMemoryBarrier(GL_BUFFER_UPDATE_BARRIER_BIT);
    glFinish();
    if (glGetError() != GL_NO_ERROR) fail("GPU dispatch");
    ++batches;
    // Yield between batches; this is a short proof, not a sustained stress test.
    const struct timespec pause = {0, 20000000};
    nanosleep(&pause, NULL);
  } while (seconds_now() - begin < duration);
  const uint32_t *data = glMapBufferRange(GL_SHADER_STORAGE_BUFFER, 0,
      ELEMENTS * sizeof(uint32_t), GL_MAP_READ_BIT);
  if (!data) fail("GPU result readback");
  for (uint32_t i = 0; i < ELEMENTS; ++i)
    if (data[i] != expected(i)) fail("GPU result differs from CPU reference");
  glUnmapBuffer(GL_SHADER_STORAGE_BUFFER);
  printf("PASS: %u GPU batches; all %u results verified. Elapsed %.2f s.\n",
         batches, ELEMENTS, seconds_now() - begin);
  glDeleteBuffers(1, &buffer);
  glDeleteProgram(program);
  glDeleteShader(shader);
  eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
  eglDestroyContext(display, context);
  eglDestroySurface(display, surface);
  eglTerminate(display);
  return 0;
}
