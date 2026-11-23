#!/usr/bin/env python3
"""Check the embedded Snapmaker U1 projects served by Duck Lab."""

import argparse
import json
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile


PLATES = ('v5-receiver-rail-fit-u1.3mf', 'v5-torso-backpack-fit-u1.3mf')
PROJECT = 'Metadata/project_settings.config'
GCODE = 'Metadata/plate_1.gcode'


def check_plate(path):
    with ZipFile(path) as archive:
        corrupt_member = archive.testzip()
        if corrupt_member:
            raise ValueError(f'Corrupt ZIP member {corrupt_member}')
        settings = json.loads(archive.read(PROJECT))
        gcode = archive.read(GCODE).decode('utf-8')

    expected = {
        'printer_model': 'Snapmaker U1',
        'printer_settings_id': 'Snapmaker U1 (0.4 nozzle)',
        'layer_height': '0.2',
        'enable_support': '1',
        'support_type': 'normal(auto)',
        'support_on_build_plate_only': '1',
    }
    for key, value in expected.items():
        if settings.get(key) != value:
            raise ValueError(f'{key} is {settings.get(key)!r}, expected {value!r}')
    if 'textured pei' not in settings.get('curr_bed_type', '').lower():
        raise ValueError(f'Expected Textured PEI, got {settings.get("curr_bed_type")!r}')
    if len(settings.get('filament_type', [])) != 1 or settings['filament_type'][0] != 'PLA':
        raise ValueError('Expected one PLA filament')

    initial_temperature = int(settings['textured_plate_temp_initial_layer'][0])
    bed_temperature = int(settings['textured_plate_temp'][0])
    if not all(55 <= value <= 65 for value in (initial_temperature, bed_temperature)):
        raise ValueError(f'Unexpected textured PEI temperatures {initial_temperature}/{bed_temperature} °C')

    for command in ('M140', 'M190'):
        startup = re.search(rf'^{command}\s+S(\d+)\b', gcode, flags=re.MULTILINE)
        if not startup or int(startup[1]) != initial_temperature:
            actual = startup[1] if startup else 'missing'
            raise ValueError(f'First {command} bed target is {actual}, expected {initial_temperature} °C')
    return initial_temperature, bed_temperature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'assets/sim')
    directory = parser.parse_args().directory
    for name in PLATES:
        try:
            initial, printing = check_plate(directory / name)
        except (BadZipFile, KeyError, OSError, ValueError) as exc:
            parser.exit(1, f'{name}: {exc}\n')
        print(f'PASS {name}: Textured PEI, {initial}/{printing} °C, build-plate-only normal supports')


if __name__ == '__main__':
    main()
