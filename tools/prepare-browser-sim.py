#!/usr/bin/env python3
"""Fetch pinned, checksummed browser engines and the upstream Duck CAD model."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / 'assets' / 'sim'
RL_COMMIT = 'fa621fc77ad9a05d69da13270e86118bdd3603fe'
MODEL_PREFIX = 'src/mjlab_microduck/robot/xgoduck/'


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    records = []

    def save(name, data, source):
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        records.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), source=source))

    packages = [
        ('three', '0.187.0', {
            'build/three.webgpu.js': 'vendor/three/three.webgpu.js',
            'build/three.core.js': 'vendor/three/three.core.js',
            'build/three.tsl.js': 'vendor/three/three.tsl.js',
            'examples/jsm/controls/OrbitControls.js': 'vendor/three/OrbitControls.js',
            'LICENSE': 'vendor/three/LICENSE',
        }),
        ('@mujoco/mujoco', '3.12.0', {
            'mujoco.js': 'vendor/mujoco/mujoco.js',
            'mujoco.wasm': 'vendor/mujoco/mujoco.wasm',
            'mujoco.d.ts': 'vendor/mujoco/mujoco.d.ts',
            'LICENSE': 'vendor/mujoco/LICENSE',
        }),
    ]
    for name, version, members in packages:
        meta = json.loads(fetch(f'https://registry.npmjs.org/{name}/{version}'))
        archive = fetch(meta['dist']['tarball'])
        integrity = 'sha512-' + base64.b64encode(hashlib.sha512(archive).digest()).decode()
        if integrity != meta['dist']['integrity']:
            raise ValueError(f'{name}: npm integrity mismatch')
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            names = tar.getnames()
            for member, destination in members.items():
                source_name = 'package/' + member
                if source_name not in names:
                    if member == 'LICENSE' and name == '@mujoco/mujoco':
                        license_url = f'https://raw.githubusercontent.com/google-deepmind/mujoco/{meta["gitHead"]}/LICENSE'
                        save(destination, fetch(license_url), dict(url=license_url, package=name, version=version))
                        continue
                    raise ValueError(f'Missing {source_name}')
                save(destination, tar.extractfile(source_name).read(), dict(package=name, version=version, integrity=integrity))
        print(f'Verified {name} {version}', flush=True)

    source = json.loads((ROOT / 'model-source.json').read_text())
    if source['commit'] != RL_COMMIT:
        raise ValueError('Unexpected model commit')
    for item in source['files']:
        url = f'https://raw.githubusercontent.com/LuwuDynamics/xgoduck_rl/{RL_COMMIT}/{item["path"]}'
        data = fetch(url)
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if blob != item['sha']:
            raise ValueError('Upstream Git blob checksum mismatch')
        relative = item['path'].removeprefix(MODEL_PREFIX)
        if relative == 'LICENSE':
            relative = 'UPSTREAM-LICENSE'
        save('model/' + relative, data, dict(url=url, commit=RL_COMMIT, git_blob=blob))
    (ROOT / 'vendor/package.json').write_text('{"type":"module","private":true}\n')
    (ROOT / 'vendor-lock.json').write_text(json.dumps(dict(schema=1, files=records), indent=2) + '\n')
    print(f'Prepared {len(records)} files, {sum(x["bytes"] for x in records) / 1e6:.1f} MB', flush=True)


if __name__ == '__main__':
    main()
