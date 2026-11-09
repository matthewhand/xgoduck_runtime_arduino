#!/usr/bin/env python3
"""Forward short taps of the UNO Q power key to the local matrix controls."""
from pathlib import Path
import struct
import time
from urllib.request import Request, urlopen

INPUT = Path('/sys/class/input')
EVENT = struct.Struct('@llHHi')  # Linux input_event, using the host's word size.
POWER_KEY = 116


def power_device():
    for node in INPUT.glob('event*'):
        try:
            if (node / 'device/name').read_text().strip() == 'pm8941_pwrkey':
                return Path('/dev/input') / node.name
        except FileNotFoundError:
            pass
    return None


def short_taps(source):
    pressed = None
    while packet := source.read(EVENT.size):
        sec, usec, kind, code, value = EVENT.unpack(packet)
        if kind == 0 and code == 3:  # SYN_DROPPED
            pressed = None
        if kind != 1 or code != POWER_KEY:
            continue
        timestamp = sec + usec * 1e-6
        if value == 1:
            pressed = timestamp
        elif value == 0 and pressed is not None:
            held = timestamp - pressed
            pressed = None
            if .035 <= held <= 1.0:
                yield


def main():
    request = Request('http://127.0.0.1:9527/api/matrix',
                      data=b'{"action":"next"}', headers={'Content-Type': 'application/json'})
    while True:
        try:
            device = power_device()
            if device:
                # Read-only and no exclusive grab. Linux still receives all key events.
                with device.open('rb', buffering=0) as source:
                    for _ in short_taps(source):
                        try:
                            with urlopen(request, timeout=1.5):
                                pass
                        except OSError as exc:
                            print(f'Matrix tap could not be delivered: {exc}', flush=True)
        except OSError as exc:
            print(f'Power key unavailable: {exc}', flush=True)
        time.sleep(2)


if __name__ == '__main__':
    main()
