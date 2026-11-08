#!/usr/bin/env python3
"""Render the UNO Q's 13×8 art and pack 3-bit pixels for the sketch."""
import argparse
import math
from pathlib import Path

WIDTH, HEIGHT = 13, 8
FRAME_MS = 64
ART_FRAMES = 144
DARK_FRAMES = 8
HEADER = Path(__file__).resolve().parents[1] / 'sketch' / 'matrix_clips.h'


def smooth(t):
    t = min(1, max(0, t))
    return t * t * (3 - 2 * t)


def escape_light(c, phase):
    z = 0j
    for i in range(88):
        z = z * z + c
        radius2 = z.real * z.real + z.imag * z.imag
        if radius2 > 16:
            count = i + 1 - math.log2(math.log2(radius2) / 2)
            bands = .56 + .44 * math.cos(count * 1.27 - phase)
            return (1 - math.exp(-max(0, count - 1) * .26)) * (1 + 4.2 * bands)
    return .08


def mandelbrot(t, center, width):
    camera = complex(-.56, 0) + (center - complex(-.56, 0)) * smooth(t * 3.2)
    scale = 3.15 * (width / 3.15) ** smooth(t) / WIDTH
    samples = (-.375, -.125, .125, .375)
    return [
        sum(escape_light(camera + scale * complex(x - 6 + dx, 3.5 - y + dy), t * 6)
            for dy in samples for dx in samples) / 16
        for y in range(HEIGHT) for x in range(WIDTH)
    ]


def glow(distance, width):
    return max(0, 1 - abs(distance) / width)


def waves(t, tide=False):
    phase = t * math.tau
    stars = ((0, 1), (3, 0), (5, 2), (8, 0), (11, 1), (12, 3), (2, 3), (9, 2))
    lights = []
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if tide:
                center = 6 + 2.5 * math.sin(phase)
                radius = math.hypot(x - center, (y - 1.9) * 1.3)
                crest = (radius - 11.0 * t) % 3.8
                ring = max(glow(crest, .92), glow(crest - 3.8, .92))
                light = 4.6 * ring * max(.24, 1 - radius * .095)
                light += 4.5 * glow(radius, 1.5)
                surface = 6 + .75 * math.sin(x * .8 - phase * 2)
                light = max(light, 2.7 * glow(y - surface, 1.2))
            else:
                surface = 5.4 + 1.24 * math.sin(x * .62 - phase * 2) + .45 * math.cos(x * 1.11 + phase)
                swell = 6.65 + .66 * math.sin(x * .83 + phase * 2 + 1.1)
                light = 4.9 * glow(y - surface, 1.2) + 2.1 * glow(y - swell, 1.05)
                moon_x, moon_y = 8.8 + 1.5 * math.cos(phase), 1.7 + .44 * math.sin(phase)
                disk = glow(math.hypot(x - moon_x, y - moon_y), 2.05)
                cut = glow(math.hypot(x - moon_x + .82, y - moon_y + .43), 1.82)
                light += 9.2 * max(0, disk - cut)
            for i, (sx, sy) in enumerate(stars):
                if (x, y) == (sx, sy):
                    twinkle = .5 + .5 * math.sin(phase * (2 + i % 3) + i * 2.1)
                    light = max(light, 2.9 * twinkle**2)
            lights.append(light)
    return lights


def pixel_field(light):
    return [light(x, y) for y in range(HEIGHT) for x in range(WIDTH)]


def ink(pixels, x, y, level):
    """Place a small light with subpixel motion on the LED grid."""
    left, top = math.floor(x), math.floor(y)
    for py in (top, top + 1):
        for px in (left, left + 1):
            if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                index = py * WIDTH + px
                pixels[index] = max(pixels[index], level * (1 - abs(px - x)) * (1 - abs(py - y)))


def sprite(pixels, pattern, left, top):
    for row, strip in enumerate(pattern):
        for col, level in enumerate(strip):
            if level.isdigit():
                ink(pixels, left + col, top + row, int(level))


def duckzilla(t):
    skyline = (2, 3, 2, 1, 2, 1, 2, 1, 2, 3, 1, 3, 2)
    pixels = pixel_field(lambda x, y: 1 + (1 if (x * 3 + y) % 4 == 0 else 0)
                         if y >= HEIGHT - skyline[x] else 0)
    rise = 3.7 * (1 - smooth(t * 4))
    sprite(pixels, ('   333   ', '  45554  ', '  4505445', '  4555554',
                    '  3554   ', '  4533   ', ' 45453   '), 0, rise)
    # A charging eye, then a sweep across the skyline from the bill.
    beam = smooth((t - .41) * 14) * (1 - smooth((t - .75) * 11))
    ink(pixels, 4, 2 + rise, 1 + 4 * beam)
    if beam > 0:
        for x in range(9, WIDTH):
            height = 2.8 + (x - 8) * (t - .41) * 3.3
            ink(pixels, x, height, beam * (5.7 if x % 2 else 4.3))
            ink(pixels, x, height + 1, beam * 2)
        for i in range(5):
            drift = (t * 5 + i * .21) % 1
            ink(pixels, 12 - drift * 3, 6 - drift * (2 + i % 3), beam * 4 * (1 - drift))
    return pixels


def duck_regatta(t):
    phase = t * math.tau
    left = -2 + 8.5 * smooth(t)
    top = 1.7 + .55 * math.sin(phase * 4)
    pixels = pixel_field(lambda x, y: 2.4 * glow(y - 6.0 - .65 * math.sin(x * 1.1 - phase * 4), 1.15))
    sprite(pixels, ('   44  ', '   5045', '2335553', '345542 ', ' 3332  '), left, top)
    for i in range(5):
        wake = (t * 5 + i / 5) % 1
        ink(pixels, left + 1 - wake * 4.0, 5.4 + wake * 1.6, 5 * (1 - wake))
    return pixels


def ghost_arcade(t):
    phase = t * math.tau
    left = 3 + 2.6 * math.sin(phase * 1.5)
    top = 1 + .65 * math.sin(phase * 4)
    pixels = pixel_field(lambda x, y: 1.8 if y == 7 and x % 3 == 0 else 0)
    fringe = '4 4 4' if math.sin(phase * 5) > 0 else ' 4 4 '
    sprite(pixels, (' 343 ', '45554', '50505', '45554', fringe), left, top)
    for i in range(4):
        progress = (t * 2 + i / 4) % 1
        ink(pixels, (i * 3.2 + 1) % WIDTH, 1 + progress * 5, 3.8 * math.sin(progress * math.pi))
    return pixels


def knife_strokes(t):
    # Stagger the paint strokes. A narrow highlight and comb marks give
    # each ridge a raised edge as the apparent light travels across it.
    def light(x, y):
        value = 0
        for i in range(5):
            progress = smooth((t - i * .115) * 3.6)
            end = -1 + progress * (13 + (i % 3) * .7)
            if progress == 0 or x > end + 1:
                continue
            ridge = 1.7 * i - .35 + .15 * x + .40 * math.sin(x * .75 + i)
            distance = y - ridge
            body = 1.8 * glow(distance, 1.1)
            rim = 3.2 * glow(distance + .36, .7)
            comb = .54 + .46 * math.sin(x * 2.4 + y * 1.5 + i * .8 - t * 9)
            value = max(value, (body + rim * comb) * min(1, end + 1 - x))
        return value

    return pixel_field(light)


def storm_impasto(t):
    def light(x, y):
        dx = x - 6 - 1.4 * math.sin(t * math.tau)
        dy = (y - 3.1) * 1.45
        radius = math.hypot(dx, dy)
        angle = math.atan2(dy, dx)
        strokes = (radius * .87 + angle * .48 - t * 2.8 + .17 * math.sin(x * 2.4 + y)) % 2.3
        ridge = glow(strokes - .59, .59)
        rim = glow(strokes - .19, .26)
        texture = .63 + .37 * math.sin(angle * 5 + radius * 2.6 + t * 5)
        return max(0, 1 - radius * .068) * (3.6 * ridge + 3.2 * rim * texture) + 2.8 * glow(radius, 1.45)

    return pixel_field(light)


def aurora_pines(t):
    phase = t * math.tau

    def light(x, y):
        top = 1.7 + 1.05 * math.sin(x * .54 - phase) + .28 * math.sin(x * 1.3 + phase)
        ribbons = 4.0 * glow(y - top, .95) + 2.8 * glow(y - top - 1.6, .9)
        tree = any(y >= tip and abs(x - trunk) <= (y - tip) // 2
                   for trunk, tip in ((1, 4), (4, 6), (9, 4), (12, 5)))
        if tree:
            return 0
        shimmer = .65 + .35 * math.sin(x * 1.42 + phase * 3)
        star = 1.8 if y == 0 and x in (1, 5, 8, 12) else 0
        horizon = 1.7 * glow(y - 6, 2.4)
        return max(star, ribbons * shimmer, horizon)

    return pixel_field(light)


def jelly_drift(t):
    phase = t * math.tau
    center = 6 + 2.4 * math.sin(phase)
    top = 2.9 + .48 * math.sin(phase * 3)
    width = 3 + .55 * math.cos(phase * 3)

    def light(x, y):
        dx, dy = x - center, y - top
        radius = math.hypot(dx / width, dy / 2)
        if dy < .3:
            return 4.8 * glow(radius - .94, .40) + 1.2 * glow(radius, .86)
        rim = 3.8 * glow(dy - .12, .8) * glow(dx, width + .5)
        threads = max(glow(dx - i * .95 - .49 * math.sin(dy * 1.25 - phase * 3 + i), .62)
                      for i in (-2, -1, 0, 1, 2))
        return max(rim, 3.9 * threads * glow(dy, 5))

    return pixel_field(light)


def fern_unfurl(t):
    pixels = [0] * (WIDTH * HEIGHT)
    growth = smooth(t * 1.75)
    breeze = math.sin(t * math.tau * 1.7)
    for step in range(36):
        u = step / 35
        if u > growth:
            break
        x = 5 + u * u * (2 + .8 * breeze)
        ink(pixels, x, 7.5 - u * 7.0, 4.5)
    for i in range(5):
        stem = .13 + i * .16
        spread = smooth((growth - stem) * 3.4)
        if spread == 0:
            continue
        base_x = 5 + stem * stem * (2 + .8 * breeze)
        base_y = 7.5 - stem * 7.0
        for side in (-1, 1):
            for step in range(1, 14):
                u = step / 13
                x = base_x + side * u * spread * (4.5 - i * .49)
                y = base_y - spread * (u * (1.0 + .55 * side) + .58 * u * u)
                ink(pixels, x, y, (5.1 - u * 1.9) * spread)
    return pixels


SCENES = (
    ('Seahorse dive', lambda t: mandelbrot(t, complex(-.743643887, .131825904), .009)),
    ('Duckzilla', duckzilla),
    ('Orbital surf', waves),
    ('Knife strokes', knife_strokes),
    ('Aurora pines', aurora_pines),
    ('Ghost arcade', ghost_arcade),
    ('Double spiral', lambda t: mandelbrot(t, complex(-1.25066, .02012), .017)),
    ('Duck regatta', duck_regatta),
    ('Jelly drift', jelly_drift),
    ('Storm impasto', storm_impasto),
    ('Fern unfurl', fern_unfurl),
    ('Gravity tide', lambda t: waves(t, tide=True)),
)


def render_clips():
    clips = []
    for _, scene in SCENES:
        frames = []
        for i in range(ART_FRAMES):
            t = i / (ART_FRAMES - 1)
            fade = min(smooth(i / 8), smooth((ART_FRAMES - i - 1) / 10))
            frames.append([min(5, round(light * fade)) for light in scene(t)])
        frames.extend([[0] * (WIDTH * HEIGHT)] * DARK_FRAMES)
        clips.append(frames)
    return clips


def pack(frame):
    packed = []
    for i in range(0, len(frame), 8):
        word = sum(level << (3 * j) for j, level in enumerate(frame[i:i + 8]))
        packed.extend(word.to_bytes(3, 'little'))
    return packed


def write_header(clips):
    lines = [
        '#pragma once', '#include <stdint.h>', '',
        '// Generated by tools/make-matrix-clips.py. Eight pixels per three bytes.',
        f'static constexpr unsigned matrixFrameMs = {FRAME_MS};',
        f'static constexpr unsigned matrixClipFrames = {ART_FRAMES + DARK_FRAMES};',
        f'static constexpr unsigned matrixClipCount = {len(SCENES)};',
        'static const uint8_t matrixClips[matrixClipCount][matrixClipFrames][39] = {',
    ]
    for (title, _), clip in zip(SCENES, clips):
        lines.append(f'  {{ // {title}')
        lines.extend('    {' + ','.join(f'0x{value:02x}' for value in pack(frame)) + '},' for frame in clip)
        lines.append('  },')
    lines.append('};')
    HEADER.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def write_preview(clips, path):
    from PIL import Image, ImageColor, ImageDraw

    colors = ['#101924', '#193350', '#235083', '#346fb2', '#569be0', '#91cbff',
              '#0a111b', '#0d1824', '#263a50', '#d0e6ff', '#89a3be']
    palette = [channel for color in colors for channel in ImageColor.getrgb(color)]
    frames = []
    for montage in zip(*clips):
        image = Image.new('P', (688, 570), 6)
        image.putpalette(palette)
        draw = ImageDraw.Draw(image)
        draw.text((15, 14), 'DUCK LAB / UNO Q MATRIX', fill=5)
        draw.text((457, 14), '12 SCENES / 13 X 8 BLUE LEDS', fill=10)
        for i, ((title, _), pixels) in enumerate(zip(SCENES, montage)):
            left, top = 14 + i % 3 * 223, 36 + i // 3 * 132
            draw.rounded_rectangle((left, top, left + 211, top + 122), radius=10, fill=7, outline=8)
            draw.text((left + 13, top + 10), title.upper(), fill=9)
            for j, level in enumerate(pixels):
                x, y = left + 17 + j % WIDTH * 14, top + 28 + j // WIDTH * 12
                draw.ellipse((x, y, x + 8, y + 8), fill=level)
        frames.append(image)
    # Start the preview after the fade-in. The firmware keeps the full loop.
    frames = frames[79:] + frames[:79]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', type=Path, help='Optional GIF preview (requires Pillow)')
    args = parser.parse_args()
    clips = render_clips()
    write_header(clips)
    if args.preview:
        write_preview(clips, args.preview)


if __name__ == '__main__':
    main()
