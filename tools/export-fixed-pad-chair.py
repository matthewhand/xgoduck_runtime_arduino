"""Export a one-piece, floor-level chair for mechanical fit checks (units: mm)."""
import argparse
import json
import math
from pathlib import Path
import struct

from manifold3d import Error, Manifold
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE_X = -65
BASE_HEIGHT = 3
POCKET_CLEARANCE = .25
WIRE_SLOT_WIDTH = 3.5
WIRE_SLOT_DEPTH = 3


def chair_body(angle, pad_inset_mm=0):
    designs = json.loads((ROOT / 'assets/sim/floor-dock-designs.json').read_text(encoding='utf8'))
    surfaces = {module['name']: module for module in designs['chairs']['Fixed pad chair']['modules']}
    backrest, lip = surfaces['Backrest'], surfaces['Seat lip']
    original = math.radians(backrest['pitch_deg'])
    lean = math.radians(angle)
    cx, _, cz = np.asarray(backrest['center_m']) * 1000
    length, width, thickness = np.asarray(backrest['size_m']) * 1000
    pivot_x = cx + length / 2 * math.cos(original)
    pivot_z = cz - length / 2 * math.sin(original)
    bottom_x = pivot_x + thickness / 2 * math.sin(lean)
    bottom_z = pivot_z + thickness / 2 * math.cos(lean)
    top_x = bottom_x - length * math.cos(lean)
    top_z = bottom_z + length * math.sin(lean)
    # Fill behind the tested backrest face. Its footprint shrinks with height.
    profile = [(BASE_X, 0), (bottom_x, 0), (bottom_x, bottom_z), (top_x, top_z), (BASE_X, top_z)]
    wedge = Manifold.hull_points([(x, y, z) for x, z in profile for y in (-width / 2, width / 2)])

    lip_x, _, lip_z = np.asarray(lip['center_m']) * 1000
    lip_length, seat_width, lip_height = np.asarray(lip['size_m']) * 1000
    lip_top = lip_z + lip_height / 2
    lip_back = lip_x - lip_length / 2
    lip_front = lip_x + lip_length / 2
    base = Manifold.cube((lip_front - BASE_X, width, BASE_HEIGHT)).translate((BASE_X, -width / 2, 0))
    seat = Manifold.cube((lip_front - lip_back, seat_width, lip_top)).translate((lip_back, -seat_width / 2, 0))
    body = wedge + base + seat
    for side in ('Left', 'Right'):
        pad = surfaces[f'{side} seat contact']
        x, y, z = np.asarray(pad['center_m']) * 1000
        pad_length, pad_width, pad_depth = np.asarray(pad['size_m']) * 1000
        y -= math.copysign(pad_inset_mm / 2, y)
        pad_width += pad_inset_mm
        pocket_floor = z - pad_depth / 2
        pocket = Manifold.cube((pad_length + 2 * POCKET_CLEARANCE, pad_width + 2 * POCKET_CLEARANCE,
                                lip_top - pocket_floor + .5))
        body -= pocket.translate((x - pad_length / 2 - POCKET_CLEARANCE,
                                  y - pad_width / 2 - POCKET_CLEARANCE, pocket_floor))
        # An open channel from the pad underside to the outer edge.
        channel = Manifold.cube((WIRE_SLOT_WIDTH, seat_width / 2 - abs(y) + .5, WIRE_SLOT_DEPTH + .5))
        body -= channel.translate((x - WIRE_SLOT_WIDTH / 2,
                                   y if y > 0 else -seat_width / 2 - .5, lip_top - WIRE_SLOT_DEPTH))
    return body


def write_stl(path, solid):
    if solid.status() != Error.NoError or len(solid.decompose()) != 1 or solid.volume() <= 0:
        raise ValueError('The chair must be one closed solid.')
    mesh = solid.to_mesh()
    vertices = mesh.vert_properties[:, :3]
    faces = vertices[mesh.tri_verts]
    normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths <= 0):
        raise ValueError('Degenerate mesh triangle.')
    normals /= lengths[:, None]
    if np.any((normals[:, 2] < -.0001) & (faces[:, :, 2].max(axis=1) > .0001)):
        raise ValueError('The chair has a downward-facing surface above the print bed.')
    with path.open('wb') as file:
        file.write(b'XGO Duck chair fit check (mm)'.ljust(80, b'\0'))
        file.write(struct.pack('<I', len(faces)))
        for normal, face in zip(normals, faces):
            file.write(struct.pack('<12fH', *normal, *face.ravel(), 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('angle', type=int, choices=(40, 45, 50))
    parser.add_argument('output', type=Path)
    parser.add_argument('--wider-pads', action='store_true', help='Extend each pad pocket 8 mm inward')
    args = parser.parse_args()
    body = chair_body(args.angle, 8 if args.wider_pads else 0)
    write_stl(args.output, body)
    print(f'{args.angle}°: one closed part, no downward-facing surfaces above the bed')


if __name__ == '__main__':
    main()
