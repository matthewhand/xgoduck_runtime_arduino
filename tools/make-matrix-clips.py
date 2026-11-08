#!/usr/bin/env python3
"""Render the UNO Q's 13×8 art and pack 3-bit pixels for the sketch."""
import argparse
import hashlib
import math
from pathlib import Path

WIDTH, HEIGHT = 13, 8
FRAME_MS = 64
ART_FRAMES = 144
DARK_FRAMES = 8
HEADER = Path(__file__).resolve().parents[1] / 'sketch' / 'matrix_clips.h'
CATALOG = HEADER.parent.parent / 'python' / 'matrix_scenes.py'


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


def tube_points(corners):
    """Sample a tube at near-uniform spacing, including both ends."""
    points = []
    for (x, y), (nx, ny) in zip(corners, corners[1:]):
        count = max(1, math.ceil(math.hypot(nx - x, ny - y) * 8))
        points.extend((x + (nx - x) * i / count, y + (ny - y) * i / count)
                      for i in range(count))
    return (*points, corners[-1])


DIGEST_IN = tube_points(((-1, 0), (1.3, 0), (2.3, 1), (2.5, 2), (3.7, 2.5), (4.7, 2.6)))
DIGEST_OUT = tube_points(((6.3, 3.5), (7.8, 4.2), (10.5, 4.2), (11.1, 5.2),
                          (10.5, 6), (7.5, 6), (7, 6.6), (7.7, 7), (13, 7)))


def digestion(t):
    """A cutaway: swallow, grind in the gizzard, then follow the winding gut."""
    pixels = [0] * (WIDTH * HEIGHT)
    for tube in (DIGEST_IN, DIGEST_OUT):
        for x, y in tube:
            ink(pixels, x, y, 1.8)

    churn = smooth((t - .25) * 15) * (1 - smooth((t - .60) * 15))
    for i in range(40):
        angle = math.tau * i / 40
        swell = 1 + churn * .11 * math.sin(t * math.tau * 9)
        x = 4.9 + 2.2 * swell * math.cos(angle)
        y = 2.45 + 1.85 * swell * math.sin(angle)
        ink(pixels, x, y, 1.6 + churn * (1 + .8 * math.cos(2 * angle - 28 * t)))

    def pellet(tube, travel, size):
        index = round(smooth(travel) * (len(tube) - 1))
        for offset, level in ((12, 1.8), (7, 2.8), (0, 6.0)):
            x, y = tube[max(0, index - offset)]
            ink(pixels, x, y, level * size)

    if t < .28:
        pellet(DIGEST_IN, t / .28, 1)
    elif t < .60:
        spin = (t - .28) / .32
        scatter = math.sin(math.pi * spin)
        for i in range(5):
            angle = 11 * spin + math.tau * i / 5
            x = 4.7 + 1.6 * spin + math.cos(angle) * scatter * (1.45 - .11 * i)
            y = 2.6 + .9 * spin + math.sin(angle) * scatter * (1.05 - .07 * i)
            ink(pixels, x, y, 5.7 - .48 * i)
    else:
        pellet(DIGEST_OUT, (t - .60) / .36, .94)
        if t > .89:
            burst = (t - .89) / .11
            for dx, dy in ((0, -1), (-1, -2), (-2, -.4), (.8, -2.4)):
                ink(pixels, 12 + dx * burst, 7 + dy * burst, 4.4 * (1 - burst))
    return pixels


def invader_position(index, t):
    x = index % 3 * 4 + round(1.1 + 1.05 * math.sin(t * math.tau * 1.6))
    y = index // 3 * 3 + int(t > .53)
    return x, y


def space_invaders(t):
    pixels = [0] * (WIDTH * HEIGHT)
    shots = ((.11, 4), (.37, 3), (.65, 5))
    bolt_time = .115
    destroyed = {index for fire, index in shots if t >= fire + bolt_time}
    for i in range(6):
        if i in destroyed:
            continue
        left, top = invader_position(i, t)
        feet = '5 5' if (int(t * 13) + i // 3) % 2 == 0 else '353'
        sprite(pixels, (' 5 ', feet), left, top)

    player = 5.5
    for fire, index in shots:
        target_x, target_y = invader_position(index, fire + bolt_time)
        target_x += 1
        if t >= fire - .12:
            player += (target_x - player) * smooth((t - fire + .12) / .12)
        if fire <= t < fire + bolt_time:
            progress = (t - fire) / bolt_time
            bolt_y = 5.7 + (target_y + .65 - 5.7) * progress
            ink(pixels, target_x, bolt_y, 6)
            ink(pixels, target_x, bolt_y + .8, 3.8)
        if fire + bolt_time <= t < fire + bolt_time + .14:
            burst = (t - fire - bolt_time) / .14
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, 0)):
                ink(pixels, target_x + dx * burst * 2, target_y + .7 + dy * burst * 1.5,
                    6 * (1 - burst))
    sprite(pixels, ('  5  ', '34543'), player - 2, 6)
    for launch, x in ((.20, 9.2), (.49, 2.3), (.79, 7.1)):
        if launch <= t < launch + .13:
            ink(pixels, x, 2 + (t - launch) / .13 * 4.2, 2.8)
    return pixels


def line(pixels, corners, level):
    for x, y in tube_points(corners):
        ink(pixels, x, y, level)


def duck_in_the_duck(t):
    pixels = [0] * (WIDTH * HEIGHT)
    if t >= .82:
        blink = 1 - glow(t - .915, .019)
        ink(pixels, 6, 3, 4.5 * blink)
        return pixels
    line(pixels, ((1, 7), (1, 1), (2, 0), (10, 0), (11, 1), (11, 7)), 1.7)
    open_amount = smooth((t - .08) / .27)
    sprite(pixels, ('  44 ', '  504', '34553', ' 332 '), 3.0, 2)
    sprite(pixels, (' 233331 ', '34234234'), 3, 6)
    pull = smooth((t - .61) / .15)
    line(pixels, ((9, 6), (8.5 - 1.9 * pull, 3.6 + 1.8 * pull)), 4)
    ink(pixels, 4 + int(t * 25) % 7, 7, 5)
    # The hatch slides upward, progressively revealing the control room.
    shutter = round(7 * (1 - open_amount))
    for y in range(shutter):
        for x in range(2, 11):
            pixels[y * WIDTH + x] = 2 if y % 2 else 1
    return pixels


def feather_foundry(t):
    pixels = pixel_field(lambda x, y: 2 if y == 7 and (x + int(t * 20)) % 3 else 0)
    line(pixels, ((0, 6), (12, 6)), 1.8)
    stroke = smooth((t - .29) / .13) * (1 - smooth((t - .47) / .16))
    head_y = 1 + 3.3 * stroke
    line(pixels, ((6, 0), (6, head_y)), 3)
    sprite(pixels, ('45554',), 4, head_y)
    if t < .47:
        ink(pixels, 6 * smooth(t / .31), 5.4, 5.8)
        if t > .38:
            for side in (-1, 1):
                ink(pixels, 6 + side * (t - .38) * 26, 4.8, 4 * stroke)
    else:
        travel = smooth((t - .53) / .47)
        x = 4.4 + 5.6 * travel
        line(pixels, ((x, 6), (x + 4, 2)), 4)
        for i in range(4):
            opened = smooth((t - .49 - i * .06) / .18)
            tip = x + 1 + i * .8
            y = 5 - i * .8
            line(pixels, ((tip - 1.5 * opened, y - .5 * opened), (tip, y),
                          (tip + 1.4 * opened, y + .45 * opened)), 2.4 * opened)
    return pixels


def pond_heist(t):
    beam = 6 + 6 * math.sin(t * math.tau * 1.4)
    pixels = pixel_field(lambda x, y: 1.7 * glow(x - beam + (7 - y) * .22, 1.85))
    sprite(pixels, ('33', '22', '22'), 10, 5)
    if t < .64:
        ink(pixels, 10.5, 4, 4.8 + .6 * math.sin(t * math.tau * 8))
    run = smooth((t - .65) / .29)
    x = -2 + 9.5 * smooth((t - .14) / .50) - 12 * run
    pose = (' 44 ', ' 503', '3442') if not run else (' 44 ', '305 ', '2443')
    sprite(pixels, pose, x, 4.0 + .22 * math.sin(t * 50))
    if .64 <= t <= .94:
        ink(pixels, x + .2, 4.8, 5)
        ink(pixels, x + 5, 7, 2.7)
    return pixels


def pocket_thunderstorm(t):
    pixels = [0] * (WIDTH * HEIGHT)
    swell = smooth(t / .31)
    for x, y, r in ((3, 2, 2), (6, 1.3, 2.4), (9, 2, 2.1)):
        for row in range(4):
            for col in range(WIDTH):
                ink(pixels, col, row, 2.8 * glow(math.hypot(col - x, row - y), r * max(.1, swell)))
    flash = max(0, 1 - abs(t - .42) / .065)
    if flash:
        line(pixels, ((6, 2), (5, 3.6), (7, 4.3), (5, 6.8)), 5.5 * flash)
        line(pixels, ((7, 4.3), (8.8, 5.6), (9.5, 6.8)), 4.5 * flash)
    for i in range(12):
        fall = (t * 4 + i * .173) % 1
        ink(pixels, (i * 7 % 13) + .32 * fall, 2.8 + fall * 4.5,
            3.2 * smooth((t - .44) / .20) * math.sin(fall * math.pi))
    ripple = smooth((t - .55) / .40)
    for x in range(WIDTH):
        ink(pixels, x, 7, ripple * (2.4 + 1.3 * math.cos(x * 1.3 - 37 * t)) * glow(x - 6, 6.5))
    return pixels


def the_ink_escapes(t):
    splash = smooth((t - .23) / .15)
    pixels = pixel_field(lambda x, y: 1.7 * splash * glow(math.hypot(x - 4.4, (y - 5.7) * 1.9), 3))
    if t < .25:
        ink(pixels, 4.4, -1 + 6.4 * (t / .25) ** 2, 6)
    else:
        run = smooth((t - .55) / .43)
        x = 4 + 10 * run
        y = 4.9 - .4 * abs(math.sin(t * 38)) if run else 4.9
        ink(pixels, x, y, 5.5)
        ink(pixels, x - .75, y + .1, 4)
        ink(pixels, x + .66, y, 4.5)
        if t > .40:
            swing = math.sin(t * 49) * smooth((t - .4) / .14)
            line(pixels, ((x - .65, y), (x - .65 + swing, 7)), 3.7)
            line(pixels, ((x + .55, y), (x + .55 - swing, 7)), 3.7)
        for dx, dy in ((-2, -1), (2, -.7), (1, -2), (-1, -1.9)):
            ink(pixels, 4 + dx * splash, 5.4 + dy * splash, 4 * (1 - splash))
    return pixels


def deep_sea_telegram(t):
    pixels = [0] * (WIDTH * HEIGHT)
    if t < .79:
        sprite(pixels, (' 32', '345', ' 32'), 0, 3)
        sprite(pixels, ('23 ', '543', '23 '), 10, 3)
    for start, origin, direction in ((.12, 3, 1), (.35, 9, -1)):
        progress = (t - start) / .19
        if 0 <= progress <= 1:
            ink(pixels, origin + direction * 6 * progress, 4, 5)
            ink(pixels, origin + direction * (6 * progress - .8), 4, 2)
    if t > .54:
        x = -9 + 23 * smooth((t - .54) / .41)
        sprite(pixels, (' 22222   ', '23333322 ', '233333332', ' 2222222 '), x, 2)
        ink(pixels, x + 6.8, 3, 4.7)
    return pixels


def impossible_staircase(t):
    pixels = [0] * (WIDTH * HEIGHT)
    level = min(4, int(t * 5))
    shift = smooth((t - .8) / .2)
    for i in range(5):
        y = 7 - i
        x = 1 + i * 2
        line(pixels, ((x, y), (x + 2, y), (x + 2, y - 1)), 2 * (1 - shift))
        line(pixels, ((x, (y + 4) % 8), (x + 2, (y + 4) % 8)), 1.8 * shift)
    up = smooth((t * 5) % 1)
    x, y = 1 + 2 * (level + up), 6 - level
    if t > .8:
        x, y = 9 + 2 * (1 - shift) - 8 * shift, 2 + 4 * shift
    ink(pixels, x, y, 5.8)
    ink(pixels, x - .8, y, 2.1)
    return pixels


def snowglobe_city(t):
    pixels = [0] * (WIDTH * HEIGHT)
    shake = smooth((t - .15) / .2) * (1 - smooth((t - .44) / .39))
    for i in range(40):
        angle = i * math.tau / 40
        ink(pixels, 6 + 5.45 * math.cos(angle) + .28 * shake * math.sin(t * 90),
            3.6 + 3.3 * math.sin(angle), 1.65)
    for x, height in ((3, 2), (5, 3), (7, 4), (9, 2)):
        for j in range(height):
            ink(pixels, x, 6 - j, (1.7 + 2.5 * smooth((t - .7 - x * .014 + j * .033) / .12)) * (1 - shake))
    for i in range(21):
        x = 2 + ((i * 17 % 31) / 31) * 8 + shake * math.sin(t * 19 + i) * 1.6
        y = (i * .34 + t * (1.1 + i % 4) + shake * math.sin(i + t * 24)) % 6
        ink(pixels, x, .6 + y, 4.4 * shake + .6)
    return pixels


def moth_theatre(t):
    lamp = 1 - smooth((t - .78) / .055)
    wing = .55 + .44 * abs(math.sin(t * 67))
    phase = t * math.tau * 2
    x, y = 4.6 + 2.2 * math.cos(phase), 2.6 + 1.2 * math.sin(phase)
    scale = 1.4 + 3.5 * smooth((t - .32) / .36)

    def stage(col, row):
        pool = lamp * (1.5 + 2.2 * glow(col - 8, 5)) * glow(row - 3.5, 4)
        shadow_x, shadow_y = (col - 8.5) / scale, (row - 4) / scale
        wings = abs(shadow_x) <= wing and abs(shadow_y + .3 * abs(shadow_x)) < .5
        return pool * (.15 if wings else 1)

    pixels = pixel_field(stage)
    ink(pixels, 2, 1, 5.2 * lamp)
    ink(pixels, x, y, 4.9 * max(lamp, .6))
    for side in (-1, 1):
        ink(pixels, x + side * wing, y - .6, 4.2 * lamp)
    return pixels


def bread_vs_gravity(t):
    flight = max(0, min(1, (t - .20) / .53))
    angle = flight * math.pi
    cs, sn = math.cos(angle), math.sin(angle)
    x, y = 3.1 + 6.3 * flight, 4.9 - 4.6 * math.sin(flight * math.pi) + 1.1 * flight
    pixels = [0] * (WIDTH * HEIGHT)
    sprite(pixels, ('33333', '24442', '22222'), 0, 5)
    if t < .74:
        for col in range(-1, 2):
            for row in range(-1, 2):
                level = 3 if row == 0 and col == 0 else 5.1
                ink(pixels, x + col * cs - row * sn, y + col * sn + row * cs, level)
    else:
        splat = smooth((t - .74) / .16)
        sprite(pixels, ('233332', ' 2442 '), 6.2, 6)
        for dx, dy in ((-2, -1), (2.5, -1.6), (.6, -2), (-.8, -1.8)):
            ink(pixels, 9.4 + dx * splat, 6.6 + dy * splat, 4.7 * (1 - .55 * splat))
    return pixels


def excavation_site(t):
    sweep = -1 + 14 * smooth(t / .72)
    pixels = pixel_field(lambda x, y: (1.6 if (x * 7 + y * 3) % 8 < 3 else .6)
                         * (1 - smooth((sweep - x) / 1.7)))
    fossil = [0] * (WIDTH * HEIGHT)
    twitch = .55 * math.sin((t - .79) * 70) * smooth((t - .79) / .1)
    line(fossil, ((4, 7), (5, 5), (6, 4)), 4.4)
    for toe_x, toe_y in ((3, 2), (6, 1), (10, 2)):
        line(fossil, ((6, 4), (toe_x, toe_y + twitch)), 3.9)
    for i, level in enumerate(fossil):
        x, y = i % WIDTH, i // WIDTH
        pixels[i] = max(pixels[i], level * smooth((sweep - x) / 1.5), 3.6 * glow(x - sweep, .9))
    return pixels


def blue_hour_train(t):
    pixels = pixel_field(lambda x, y: 1.4 if y >= 6 - x * .20 - .8 * math.sin(x * .64) else 0)
    train = -3 + 17.0 * t
    for i in range(7):
        x = train - i
        if 7.7 <= x <= 10.8:
            continue
        ink(pixels, x, 5, 5.8 if i == 0 else (3.6 if i % 2 else 1.9))
        ink(pixels, x, 6, 2.8)
    line(pixels, ((7.7, 7), (7.7, 4.3), (8.4, 3.6), (10.1, 3.6),
                  (10.8, 4.3), (10.8, 7)), 2.7)
    return pixels


ENCORE = (
    ('The duck inside the duck', duck_in_the_duck),
    ('Feather foundry', feather_foundry),
    ('Pond heist', pond_heist),
    ('Pocket thunderstorm', pocket_thunderstorm),
    ('The ink escapes', the_ink_escapes),
    ('Deep sea telegram', deep_sea_telegram),
    ('The impossible staircase', impossible_staircase),
    ('Snowglobe city', snowglobe_city),
    ('Moth theatre', moth_theatre),
    ('Bread vs. gravity', bread_vs_gravity),
    ('Excavation site', excavation_site),
    ('Blue hour train', blue_hour_train),
)

MARQUEE_FONT = {
    ' ': (0,0,0,0,0), ':': (0,2,0,2,0),
    '0': (7,5,5,5,7), '4': (5,5,7,1,1),
    'A': (2,5,7,5,5), 'B': (6,5,6,5,6), 'C': (7,4,4,4,7),
    'D': (6,5,5,5,6), 'E': (7,4,6,4,7), 'F': (7,4,6,4,4),
    'G': (7,4,5,5,7), 'H': (5,5,7,5,5), 'I': (7,2,2,2,7),
    'J': (1,1,1,5,7), 'K': (5,5,6,5,5), 'L': (4,4,4,4,7),
    'M': (5,7,7,5,5), 'N': (5,7,7,7,5), 'O': (7,5,5,5,7),
    'P': (6,5,6,4,4), 'Q': (7,5,5,7,1), 'R': (6,5,6,5,5),
    'S': (7,4,7,1,7), 'T': (7,2,2,2,2), 'U': (5,5,5,5,7),
    'V': (5,5,5,5,2), 'W': (5,5,7,7,5), 'X': (5,5,2,5,5),
    'Y': (5,5,2,2,2), 'Z': (7,1,2,4,7),
}

MARQUEE_MESSAGES = (
    'QUACK LOADING', 'SEND PEAS', 'WADDLE DRIVE', 'DUCKOS 404',
    'WIFI: POND', 'WRONG BIRD', 'BREAD BUFFER', 'QUACK TAX DUE',
    'TAILGATE ME', 'MAXIMUM DUCK', 'EGG IN DEV', 'I EAT BUGS',
)


def marquee(t, message, lane):
    pixels = [0] * (WIDTH * HEIGHT)
    # Whole-column motion keeps the little characters crisp. Two frames
    # per column gives the eye 128 ms to read each position.
    frame = round(t * (ART_FRAMES - 1))
    left = WIDTH - (frame - 6) // 2
    for i, char in enumerate(message):
        start = left + i * 4
        if start + 2 < 0 or start >= WIDTH:
            continue
        for y, row in enumerate(MARQUEE_FONT[char], 1):
            for col in range(3):
                x = start + col
                if 0 <= x < WIDTH and row & (4 >> col):
                    pixels[y * WIDTH + x] = 5

    # Dim moving trim stays outside the lettering.
    for x in range(WIDTH):
        if (x + frame // 4 + lane) % 5 == 0:
            pixels[x] = 1
        if (x - frame // 5 + lane) % 6 < 2:
            pixels[7 * WIDTH + x] = 2
    return pixels


MARQUEES = tuple((message, lambda t, text=message, lane=i: marquee(t, text, lane))
                 for i, message in enumerate(MARQUEE_MESSAGES))


SCENES = (
    ('Seahorse dive', lambda t: mandelbrot(t, complex(-.743643887, .131825904), .009)),
    ('Duckzilla', duckzilla),
    ('Orbital surf', waves),
    ('Knife strokes', knife_strokes),
    ('Aurora pines', aurora_pines),
    ('Ghost arcade', ghost_arcade),
    ('Duck digestion', digestion),
    ('Double spiral', lambda t: mandelbrot(t, complex(-1.25066, .02012), .017)),
    ('Duck regatta', duck_regatta),
    ('Jelly drift', jelly_drift),
    ('Storm impasto', storm_impasto),
    ('Fern unfurl', fern_unfurl),
    ('Space invaders', space_invaders),
    ('Gravity tide', lambda t: waves(t, tide=True)),
) + ENCORE + MARQUEES


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
    names = tuple(name for name, _ in SCENES)
    catalog_id = int.from_bytes(hashlib.sha256('\0'.join(names).encode()).digest()[:2], 'big')
    lines = [
        '#pragma once', '#include <stdint.h>', '',
        '// Generated by tools/make-matrix-clips.py. Eight pixels per three bytes.',
        f'static constexpr unsigned matrixFrameMs = {FRAME_MS};',
        f'static constexpr unsigned matrixClipFrames = {ART_FRAMES + DARK_FRAMES};',
        f'static constexpr unsigned matrixClipCount = {len(SCENES)};',
        f'static constexpr unsigned matrixCatalogId = {catalog_id};',
        'static const uint8_t matrixClips[matrixClipCount][matrixClipFrames][39] = {',
    ]
    for (title, _), clip in zip(SCENES, clips):
        lines.append(f'  {{ // {title}')
        lines.extend('    {' + ','.join(f'0x{value:02x}' for value in pack(frame)) + '},' for frame in clip)
        lines.append('  },')
    lines.append('};')
    HEADER.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    marquee_from = len(names) - len(MARQUEES)
    catalog = ['# Generated by tools/make-matrix-clips.py.', f'CATALOG_ID = {catalog_id}',
               f'ENCORE_FROM = {marquee_from - len(ENCORE)}', f'MARQUEE_FROM = {marquee_from}',
               'SCENE_NAMES = (']
    catalog.extend(f'    {name!r},' for name in names)
    catalog.append(')')
    CATALOG.write_text('\n'.join(catalog) + '\n', encoding='utf-8', newline='\n')


def write_preview(clips, path, titles):
    from PIL import Image, ImageColor, ImageDraw

    colors = ['#101924', '#193350', '#235083', '#346fb2', '#569be0', '#91cbff',
              '#0a111b', '#0d1824', '#263a50', '#d0e6ff', '#89a3be']
    palette = [channel for color in colors for channel in ImageColor.getrgb(color)]
    cols = min(3, len(clips))
    rows = math.ceil(len(clips) / cols)
    frames = []
    for montage in zip(*clips):
        image = Image.new('P', (19 + cols * 223, 42 + rows * 132), 6)
        image.putpalette(palette)
        draw = ImageDraw.Draw(image)
        draw.text((15, 14), 'DUCK LAB / UNO Q MATRIX', fill=5)
        if cols > 1:
            draw.text((image.width - 135, 14), '13 X 8 BLUE LEDS', fill=10)
        for i, (title, pixels) in enumerate(zip(titles, montage)):
            left, top = 14 + i % cols * 223, 36 + i // cols * 132
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
    parser.add_argument('--preview-scene', action='append', choices=[title for title, _ in SCENES],
                        help='Preview just this scene. Repeat to select more than one.')
    args = parser.parse_args()
    clips = render_clips()
    write_header(clips)
    if args.preview:
        selected = [(title, clip) for (title, _), clip in zip(SCENES, clips)
                    if not args.preview_scene or title in args.preview_scene]
        titles, preview_clips = zip(*selected)
        write_preview(preview_clips, args.preview, titles)


if __name__ == '__main__':
    main()
