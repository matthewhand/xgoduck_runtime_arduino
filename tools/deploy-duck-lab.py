#!/usr/bin/env python3
"""Package and install the Build & Test release over the board's existing SSH connection."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from shutil import copy2
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


REPO = Path(__file__).resolve().parents[1]
APP = Path.home() / 'ArduinoApps/xgo-duck'
ROOT_ASSETS = ('index.html', 'calibrate.html', 'calibrate.js', 'servo.html', 'servo.js',
               'sim/physical-trial.mjs', 'sim/trial-report.mjs')
LAB_ASSETS = (
    'sim/sim.css', 'sim/lab-entry.css', 'sim/matrix-ui.mjs', 'sim/build-test.mjs', 'sim/trial-report.mjs',
    'sim/stock-replay.json', 'sim/v5-receiver-rail-fit-u1.3mf',
    'sim/v5-torso-backpack-fit-u1.3mf', 'sim/sim-ui.mjs', 'sim/walk-ui.mjs', 'experimental.html',
    'build-test.html', 'simulate.html',
)
COMPANION_PAGES = ('attachments.html', 'camera-replay.html', 'dock-vision.html', 'tail-sizing.html')
ALIASES = ('simulate.html', 'build-test.html', 'experimental.html', *COMPANION_PAGES)
BACKEND = ('python/main.py', 'python/controller.py', 'python/walk_lab.py')
MANAGED_BACKEND = ('python/physical_trial.py',)
EXPERIMENT_BASE = (*COMPANION_PAGES, 'sim/qualification-replay.mjs',
                   'sim/vendor/three/three.webgpu.js', 'sim/vendor/mujoco/mujoco.wasm')
STAMP = 'assets/experiments/build-test-release.json'
LEGACY_POND = 'assets/pond-demo-legacy.html'
LEGACY_POND_HTML = '81cc490dffd34e5e07bef67a0fbb42dab31e7c89196c569cf527ae689b82812a'
LEGACY_POND_MODULE = '51742f55993dbd2072b9fe95b7f35a3a795bef571f730f75a0e262d320013705'
FILES = (*BACKEND, *MANAGED_BACKEND, *(f'assets/{name}' for name in ROOT_ASSETS),
         *(f'assets/experiments/{name}' for name in LAB_ASSETS),
         *(f'assets/{name}' for name in ALIASES))


def revision(ref):
    return git('rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args])


def digest(data):
    return sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def alias(page, legacy_pond=False):
    destination = f'/experiments/{page}'
    script = f'location.replace({destination!r} + location.search + location.hash)'
    if legacy_pond:
        script = f'''const query = new URLSearchParams(location.search);
const canonical = ['stock', 'lab', 'mods', 'teeth', 'tusks', 'tail', 'skin', 'dock', 'hardware', 'skates', 'replay'];
const pond = query.get('demo') === '1' && !canonical.some(key => query.has(key));
location.replace((pond ? '/pond-demo-legacy.html' : {destination!r}) + location.search + location.hash)'''
    return f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Duck Lab</title>
<script>{script}</script>
<a href="{destination}">Open Duck Lab</a></html>
'''.encode()


def package(destination, ref, base):
    release = revision(ref)
    base = revision(base or f'{release}^')
    files = {name: git('cat-file', 'blob', f'{release}:{name}') for name in (*BACKEND, *MANAGED_BACKEND)}
    files.update({f'assets/{name}': git('cat-file', 'blob', f'{release}:assets/{name}')
                  for name in ROOT_ASSETS})
    files.update({f'assets/experiments/{name}': git('cat-file', 'blob', f'{release}:assets/{name}')
                  for name in LAB_ASSETS})
    files.update({f'assets/{name}': alias(name) for name in ALIASES})
    baseline = {name: git('cat-file', 'blob', f'{base}:{name}') for name in BACKEND}
    manifest = {'commit': release, 'base': base, 'files': {name: digest(data) for name, data in files.items()},
                'backend_base': {name: digest(data) for name, data in baseline.items()}}
    with ZipFile(destination, 'w') as archive:
        for prefix, contents in (('files', files), ('base', baseline)):
            for name, data in contents.items():
                archive.writestr(ZipInfo(f'{prefix}/{name}'), data, ZIP_DEFLATED)
        archive.writestr(ZipInfo('manifest.json'), json_bytes(manifest), ZIP_DEFLATED)
    return release


def verified_files(archive, prefix, expected, allowed):
    if set(expected) != set(allowed):
        raise ValueError(f'Unexpected {prefix} file list')
    payload = {}
    for name, checksum in expected.items():
        data = archive.read(f'{prefix}/{name}')
        if digest(data) != checksum:
            raise ValueError(f'Checksum mismatch for {name}')
        payload[name] = data
    return payload


def merge_python(work, name, current, base, incoming):
    work.mkdir(exist_ok=True)
    paths = [work / part for part in ('current', 'base', 'incoming')]
    for path, data in zip(paths, (current, base, incoming)):
        path.write_bytes(data.replace(b'\r\n', b'\n'))
    result = subprocess.run(['git', 'merge-file', '-p', *map(str, paths)], capture_output=True)
    if result.returncode:
        raise ValueError(f'Unable to merge {name} cleanly. No live files were changed.')
    compile(result.stdout, name, 'exec')
    return result.stdout


def app_file(app, name):
    path = app / name
    if not path.parent.is_dir() or not path.parent.resolve().is_relative_to(app.resolve()):
        raise ValueError(f'Missing or unsafe app directory for {name}')
    if path.is_symlink():
        raise ValueError(f'Unexpected symlink at {name}')
    return path


def legacy_pond_snapshot(app):
    module = app / 'assets/sim/sim-ui.mjs'
    if not module.is_file() or digest(module.read_bytes()) != LEGACY_POND_MODULE:
        return None
    for name in (LEGACY_POND, 'assets/simulate.html'):
        page = app_file(app, name)
        if page.is_file():
            data = page.read_bytes()
            if digest(data.replace(b'\r\n', b'\n')) == LEGACY_POND_HTML:
                return data
    return None


def install(bundle, app=APP):
    state = bundle.parent
    for name in EXPERIMENT_BASE:
        if not (app / 'assets/experiments' / name).is_file():
            raise ValueError(f'Install the Duck Lab experiments before deploying this update. Missing {name}.')
    with ZipFile(bundle) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        files = verified_files(archive, 'files', manifest['files'], FILES)
        baseline = verified_files(archive, 'base', manifest['backend_base'], BACKEND)
    legacy = legacy_pond_snapshot(app)
    if legacy is not None:
        files.pop('assets/simulate.html')
        files[LEGACY_POND] = legacy
        files['assets/simulate.html'] = alias('simulate.html', legacy_pond=True)
    backend_changed = []
    for name in BACKEND:
        current = app_file(app, name).read_bytes()
        files[name] = merge_python(state / 'merge', name, current, baseline[name], files[name])
        if files[name] != current:
            backend_changed.append(name)
    for name in MANAGED_BACKEND:
        compile(files[name], name, 'exec')
        target = app_file(app, name)
        if not target.exists() or target.read_bytes() != files[name]:
            backend_changed.append(name)
    deployed = {'commit': manifest['commit'], 'base': manifest['base'],
                'files': {name: digest(data) for name, data in files.items()}}
    files[STAMP] = json_bytes(deployed)
    targets = {name: app_file(app, name) for name in files}
    changes = {name: data for name, data in files.items()
               if not targets[name].exists() or targets[name].read_bytes() != data}
    stage = state / 'stage'
    backup = state / 'backup'
    stage.mkdir()
    backup.mkdir()
    record = {}
    for name, data in changes.items():
        target = targets[name]
        staged = stage / name
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        original_hash = None
        if target.exists():
            original = backup / name
            original.parent.mkdir(parents=True, exist_ok=True)
            copy2(target, original)
            original_hash = digest(original.read_bytes())
        staged.chmod(target.stat().st_mode & 0o777 if original_hash else 0o644)
        record[name] = {'original': original_hash, 'installed': digest(data)}
    (backup / 'manifest.json').write_bytes(json_bytes(record))

    applied = []
    try:
        for name in changes:
            (stage / name).replace(targets[name])
            applied.append(name)
        for name, data in files.items():
            if targets[name].read_bytes() != data:
                raise OSError(f'Installed checksum mismatch for {name}')
    except BaseException:
        restore(backup, app, applied)
        raise
    print(json.dumps({'commit': deployed['commit'], 'files_changed': len(changes),
                      'backend_changed': backend_changed, 'rollback': str(backup)}))


def restore(backup, app=APP, names=None):
    record = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
    manual = names is None
    names = list(record) if names is None else names
    targets = {}
    for name in names:
        if name not in (*FILES, LEGACY_POND, STAMP):
            raise ValueError(f'Unexpected rollback path {name}')
        target = app_file(app, name)
        original = record[name]['original']
        if manual:
            current = digest(target.read_bytes()) if target.exists() else None
            if current == original:
                continue
            if current != record[name]['installed']:
                raise ValueError(f'{name} changed since this installation. Rollback was stopped.')
        if original and digest((backup / name).read_bytes()) != original:
            raise ValueError(f'Backup checksum mismatch for {name}')
        targets[name] = target
    for name, target in reversed(targets.items()):
        if record[name]['original']:
            staged = backup / name
            mode = staged.stat().st_mode & 0o777
            with TemporaryDirectory(dir=target.parent) as directory:
                previous = Path(directory) / target.name
                copy2(staged, previous)
                previous.chmod(mode)
                previous.replace(target)
        else:
            target.unlink()


def deploy(bundle, host, address):
    connection = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8']
    if address:
        connection += ['-o', f'HostName={address}']
    ssh = ['ssh', *connection, host]
    remote = subprocess.check_output([*ssh, 'umask 077; mkdir -p "$HOME/.duck-lab-deploy" && '
                                     'mktemp -d "$HOME/.duck-lab-deploy/duck-lab.XXXXXX"'], text=True).strip()
    if not re.fullmatch(r'/home/[a-z_][a-z0-9_-]*/\.duck-lab-deploy/duck-lab\.[a-zA-Z0-9]{6}', remote):
        raise ValueError('Unexpected remote staging directory')
    subprocess.run(['scp', *connection, str(bundle), f'{host}:{remote}/release.zip'], check=True)
    subprocess.run(['scp', *connection, str(Path(__file__).resolve()), f'{host}:{remote}/install.py'], check=True)
    subprocess.run([*ssh, 'flock -n "$HOME/.duck-lab-deploy/build-test.lock" '
                    f'python3 -B {remote}/install.py --install {remote}/release.zip'], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD', help='Committed release revision to package')
    parser.add_argument('--base', help='Previous backend revision for the three-way merge, defaulting to the release parent')
    parser.add_argument('--output', type=Path, help='Write the release bundle to a local path')
    parser.add_argument('--host', help='Board SSH host alias')
    parser.add_argument('--address', help='Override the SSH alias address while preserving its host identity')
    parser.add_argument('--install', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--restore', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.install:
        install(args.install)
        return
    if args.restore:
        restore(args.restore)
        return
    if not args.output and not args.host:
        parser.error('choose --output, --host, or both')
    if any(value and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', value)
           for value in (args.host, args.address)):
        parser.error('use a plain SSH host alias and Wi-Fi address')
    if args.output and args.output.exists():
        parser.error(f'output already exists: {args.output}')

    with TemporaryDirectory(prefix='duck-lab-') as directory:
        bundle = args.output or Path(directory) / 'release.zip'
        release = package(bundle, args.ref, args.base)
        if args.output:
            print(f'Packaged {release} at {bundle}')
        if args.host:
            deploy(bundle, args.host, args.address)


if __name__ == '__main__':
    main()
