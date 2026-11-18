"""Export the five marked dock tiles as two-colour 3MF components, in millimetres."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from manifold3d import Error, Manifold

ROOT = Path(__file__).resolve().parents[1]
CORE = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
MATERIALS = ('#F2F1E8FF', '#252522FF')


def mesh_resource(resources, ident, name, material, solid):
    if solid.status() != Error.NoError or solid.volume() <= 0:
        raise ValueError(f'Invalid solid for {name}')
    obj = ET.SubElement(resources, 'object', id=str(ident), type='model',
                        name=name, pid='1', pindex=str(material))
    mesh = ET.SubElement(obj, 'mesh')
    vertices = ET.SubElement(mesh, 'vertices')
    triangles = ET.SubElement(mesh, 'triangles')
    geometry = solid.to_mesh()
    for x, y, z in geometry.vert_properties[:, :3]:
        ET.SubElement(vertices, 'vertex', x=f'{x:.6f}', y=f'{y:.6f}', z=f'{z:.6f}')
    for a, b, c in geometry.tri_verts:
        ET.SubElement(triangles, 'triangle', v1=str(a), v2=str(b), v3=str(c))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    layout = json.loads((ROOT / 'assets/sim/dock-vision-layout.json').read_text(encoding='utf8'))
    base_h, ink_h = (layout[key]*1000 for key in ('plate_thickness_m', 'ink_thickness_m'))
    model = ET.Element('model', unit='millimeter', xmlns=CORE)
    resources = ET.SubElement(model, 'resources')
    palette = ET.SubElement(resources, 'basematerials', id='1')
    for name, color in zip(('Light base', 'Dark pattern'), MATERIALS):
        ET.SubElement(palette, 'base', name=name, displaycolor=color)
    build = ET.SubElement(model, 'build')
    for i, panel in enumerate(layout['panels']):
        size = panel['size_m']*1000
        pitch = size/len(panel['bitmap'])
        ident = 2+3*i
        base = Manifold.cube((size, size, base_h))
        ink = Manifold()
        for row, bits in enumerate(reversed(panel['bitmap'])):
            for col, bit in enumerate(bits):
                if bit == '1':
                    # 0.02 mm overlap also joins diagonal grid contacts into solid material.
                    cell = Manifold.cube((pitch+.02, pitch+.02, ink_h))
                    ink += cell.translate((col*pitch-.01, row*pitch-.01, base_h))
        name = panel['name']
        mesh_resource(resources, ident, name+' base', 0, base)
        mesh_resource(resources, ident+1, name+' pattern', 1, ink)
        obj = ET.SubElement(resources, 'object', id=str(ident+2), type='model', name=name)
        parts = ET.SubElement(obj, 'components')
        for part in (ident, ident+1):
            ET.SubElement(parts, 'component', objectid=str(part))
        x, y = i%3*40, i//3*40
        ET.SubElement(build, 'item', objectid=str(ident+2),
                      transform=f'1 0 0 0 1 0 0 0 1 {x} {y} 0')
    with ZipFile(args.output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="utf-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        archive.writestr('_rels/.rels', '<?xml version="1.0" encoding="utf-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" '
            'Target="/3D/3dmodel.model"/></Relationships>')
        archive.writestr('3D/3dmodel.model', ET.tostring(model, encoding='utf-8', xml_declaration=True))


if __name__ == '__main__':
    main()
