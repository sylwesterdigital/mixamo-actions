#!/usr/bin/env python3
"""Fail-closed local Mixamo Actions ZIP installer, no third-party dependencies.

The watcher calls this with a fully written release ZIP. No remote system is touched
until local validation, upgrade, Flask restart and health probes have passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


def info(message):
    print('[mixamo-update]', message, flush=True)


def load_release(zip_path: Path, destination: Path):
    """Reject traversal, links, unlisted payloads, and digest mismatches before writing."""
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        if len(infos) > 300 or sum(m.file_size for m in infos) > 75_000_000:
            raise RuntimeError('Package exceeds update limits')
        all_files = set()
        for member in infos:
            name = member.filename
            p = PurePosixPath(name)
            if not name or name.startswith('/') or '\\' in name or '..' in p.parts:
                raise RuntimeError(f'Unsafe ZIP path: {name!r}')
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError('ZIP symlinks are forbidden')
            if not member.is_dir():
                if name in all_files: raise RuntimeError('Duplicate path in ZIP')
                all_files.add(name)
        if 'release.json' not in all_files:
            raise RuntimeError('Missing release.json')
        metadata = json.loads(archive.read('release.json'))
        version = metadata.get('version', '')
        if not isinstance(version, str) or not __import__('re').fullmatch(r'\d+\.\d+\.\d+', version):
            raise RuntimeError('Malformed version')
        expected = metadata.get('files', {})
        if not isinstance(expected, dict) or not expected or all_files != set(expected) | {'release.json'}:
            raise RuntimeError('Release manifest does not match ZIP file list')
        for name, digest in expected.items():
            if not any(name.startswith(prefix) for prefix in ('core/', 'site/', 'ops/', 'tests/')) and name not in (
                'VERSION', 'updates-log.md', 'README.md', '.gitignore', 'mixamo-studio-watch.sh', 'mixamo-watch.env.example'):
                raise RuntimeError(f'Path not permitted in release: {name}')
            if not isinstance(digest, str) or len(digest) != 64:
                raise RuntimeError('Invalid release digest')
            payload = archive.read(name)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise RuntimeError(f'Hash mismatch: {name}')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        (destination / 'release.json').write_bytes(archive.read('release.json'))
    return metadata


def version_parts(value):
    return tuple(int(v) for v in value.split('.'))


def run_checked(command, cwd, timeout=240):
    info('RUN ' + ' '.join(map(str, command)))
    subprocess.run(command, cwd=cwd, check=True, timeout=timeout)


def get_old_version(root):
    installed = root / 'VERSION'
    if not installed.is_file(): return '0.0.0'
    s = installed.read_text().strip()
    return s if __import__('re').fullmatch(r'\d+\.\d+\.\d+', s) else '0.0.0'


def process_is_studio(pid):
    try:
        output = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True).strip()
        return 'flask_app.py' in output
    except (OSError, subprocess.CalledProcessError):
        return False


def process_workdir(pid):
    """Resolve local listener cwd on macOS (lsof) or Linux (/proc)."""
    proc_cwd = Path(f'/proc/{pid}/cwd')
    try:
        return proc_cwd.resolve(strict=True)
    except (OSError, RuntimeError):
        pass
    try:
        output = subprocess.check_output(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                                         text=True, stderr=subprocess.DEVNULL, timeout=3)
        for line in output.splitlines():
            if line.startswith('n/'):
                return Path(line[1:]).resolve()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    return None


def managed_pid(root):
    """Find an owned Studio server, including one started with legacy ./start.sh."""
    expected = (root / 'core').resolve()
    pidfile = root / 'updates/.state/studio.pid'
    try:
        pid = int(pidfile.read_text().strip())
        if process_is_studio(pid) and process_workdir(pid) == expected:
            return pid
    except (OSError, ValueError):
        pass
    # Legacy start.sh didn't save a PID. Accept only a listener whose cwd is our core.
    try:
        result = subprocess.run(['lsof', '-nP', '-tiTCP:5055', '-sTCP:LISTEN'],
                                text=True, capture_output=True, timeout=4)
        for line in result.stdout.splitlines():
            if line.strip().isdigit():
                pid = int(line)
                if process_is_studio(pid) and process_workdir(pid) == expected:
                    return pid
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def describe_port_5055():
    """Return the local listener PID/command for an actionable, non-destructive error."""
    try:
        result = subprocess.run(['lsof', '-nP', '-tiTCP:5055', '-sTCP:LISTEN'],
                                text=True, capture_output=True, timeout=4)
        pids = [x for x in result.stdout.splitlines() if x.isdigit()]
    except (OSError, subprocess.TimeoutExpired):
        pids = []
    lines = []
    for value in pids:
        try:
            cmd = subprocess.check_output(['ps', '-p', value, '-o', 'command='],
                                          text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            cmd = '(command unavailable)'
        lines.append(f'PID {value}: {cmd}')
    return '; '.join(lines) or 'Process information unavailable; use lsof -nP -iTCP:5055 -sTCP:LISTEN'


def preflight_service_ownership(root):
    """Check BEFORE replacing files or installing packages.

    We must never stop, restart, or overwrite a service belonging to some
    other working directory, even when both are Flask servers on 5055.
    """
    if port_available() or managed_pid(root) is not None:
        return
    raise RuntimeError(
        'Port 5055 is occupied by an application not confirmed to belong to this repository. '
        'No source files were changed. ' + describe_port_5055() + '. '
        'Inspect it using lsof -nP -iTCP:5055 -sTCP:LISTEN and '
        'ps -p PID -o command=; stop only the verified old instance, then retry.'
    )

def port_available(port=5055):
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def stop_studio(root):
    pid = managed_pid(root)
    if not pid:
        if not port_available():
            raise RuntimeError('Port 5055 is occupied by a process outside this installation: ' + describe_port_5055())
        return
    info(f'Stopping managed Flask PID {pid}')
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not process_is_studio(pid): break
        time.sleep(.1)
    if process_is_studio(pid):
        os.kill(pid, signal.SIGKILL)
    (root / 'updates/.state/studio.pid').unlink(missing_ok=True)
    for _ in range(50):
        if port_available(): return
        time.sleep(.1)
    raise RuntimeError('Flask did not release port 5055')


def start_studio(root, wanted_version):
    core = root / 'core'
    py = core / '.venv/bin/python'
    if not py.is_file():
        raise RuntimeError('Missing core/.venv/bin/python')
    if not port_available():
        raise RuntimeError('Port 5055 occupied; will not terminate an unknown process')
    state = root / 'updates/.state'
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'studio.log').open('ab') as output:
        env = os.environ.copy()
        env['MIXAMO_NO_BROWSER'] = '1'
        proc = subprocess.Popen([str(py), '-u', 'flask_app.py'], cwd=core, env=env,
                                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                start_new_session=True)
    (state / 'studio.pid').write_text(str(proc.pid) + '\n')
    for _ in range(70):
        if proc.poll() is not None:
            raise RuntimeError(f'Flask quit immediately ({proc.returncode}); see updates/.state/studio.log')
        try:
            with urllib.request.urlopen('http://127.0.0.1:5055/api/release', timeout=.8) as response:
                meta = json.load(response)
                if meta.get('version') == wanted_version:
                    info(f'Flask healthy: version {wanted_version}, PID {proc.pid}')
                    return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('Flask did not pass /api/release health probe')


def wait_until_idle(root, max_seconds=7200):
    """Read-only query. Wait for active Blender/Playwright jobs before restart."""
    deadline = time.monotonic() + max_seconds
    while not port_available():
        try:
            with urllib.request.urlopen('http://127.0.0.1:5055/api/update-readiness', timeout=2) as r:
                response = json.load(r)
            if response.get('ready'): return
            info('Active Mixamo job detected; waiting before upgrade…')
        except Exception:
            # Older releases do not have readiness endpoint. Check for known active
            # Blender/Pipeline child processes rather than assuming idle.
            running = subprocess.run(['pgrep', '-fl', 'mixamo_pipeline.py|blender_build.py'],
                                     text=True, capture_output=True)
            if running.returncode != 0: return
            info('Existing Blender/Mixamo pipeline appears busy; waiting…')
        if time.monotonic() > deadline:
            raise RuntimeError('Active job did not finish before maintenance timeout; update postponed')
        time.sleep(5)


def ensure_dependencies(root):
    core = root / 'core'
    py = core / '.venv/bin/python'
    if not py.exists():
        run_checked([sys.executable, '-m', 'venv', '.venv'], core, 90)
    run_checked([str(py), '-m', 'pip', 'install', '-r', 'requirements.txt'], core, 240)
    run_checked([str(py), '-m', 'compileall', '-q', 'flask_app.py', 'mixamo_pipeline.py', 'mixamo_browser.py', 'blender_build.py'], core, 45)
    run_checked([str(py), '-m', 'unittest', 'discover', '-s', 'tests', '-v'], core, 120)
    node = shutil.which('node')
    if node:
        for js in ['static/studio.js', 'static/release-watch.js', 'mixamo_motion_collector.js']:
            run_checked([node, '--check', js], core, 40)


def copy_into_place(stage, root, paths):
    for path in paths:
        source, target = stage / path, root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # shell scripts lose executable bits in validated ZIP payloads.
    for name in ['mixamo-studio-watch.sh', 'core/start.sh', 'core/brave_session.sh',
                 'ops/deploy-homepage.sh', 'ops/build_release.py']:
        target = root / name
        if target.exists(): target.chmod(target.stat().st_mode | 0o111)


def still_matches_previous_release(root, name):
    """Treat release-installed tracked edits as safe when their bytes remain unmodified.

    The normal sequence is install -> test -> restart -> publish to Git. If the
    publish is disabled or temporarily fails, the source differs from HEAD but
    still matches the last verified release manifest. Do not confuse that with
    a user's independent edits.
    """
    file = root / name
    if not file.is_file():
        return False
    try:
        previous = json.loads((root / 'release.json').read_text())
        if name == 'release.json':
            return previous.get('version') == (root / 'VERSION').read_text().strip()
        digest = previous.get('files', {}).get(name)
        return isinstance(digest, str) and hashlib.sha256(file.read_bytes()).hexdigest() == digest
    except (OSError, ValueError, TypeError):
        return False


def git_staged_conflicts(root, paths):
    """Do not overwrite files with staged work that may be an intended commit.

    Backing up only the working tree cannot preserve a user's Git index state.
    """
    if not (root / '.git').exists():
        return []
    command = ['git', 'diff', '--cached', '--name-only', '--'] + list(paths)
    outcome = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if outcome.returncode:
        raise RuntimeError('Could not inspect staged Git changes; refusing update')
    return [line for line in outcome.stdout.splitlines() if line]


def ensure_regular_targets(root, paths):
    """Existing release-managed paths must not be symbolic links."""
    for name in paths:
        current = root
        for part in PurePosixPath(name).parts:
            current = current / part
            if current.is_symlink():
                raise RuntimeError(f'Refusing release target containing a symlink: {name}')
        if current.exists() and not current.is_file():
            raise RuntimeError(f'Refusing non-file release target: {name}')


def git_has_conflicts(root, paths):
    if not (root / '.git').exists(): return []
    cmd = ['git', 'diff', '--name-only', '--'] + list(paths)
    outcome = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if outcome.returncode: return []
    return [line for line in outcome.stdout.splitlines() if line]


def install(zip_file, root, verify_only=False):
    root.mkdir(parents=True, exist_ok=True)
    state = root / 'updates/.state'; state.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mixamo-verify-') as scratch:
        stage = Path(scratch) / 'stage'; stage.mkdir()
        meta = load_release(zip_file, stage)
        version = meta['version']
        if zip_file.name != f'mixamo-actions-v{version}.zip':
            raise RuntimeError(f'ZIP filename does not match release version {version}')
        old = get_old_version(root)
        if verify_only:
            info(f'PASS manifest v{version} ({len(meta["files"])} checked files)')
            return True
        if version_parts(version) <= version_parts(old) and os.environ.get('MIXAMO_FORCE_REINSTALL') != '1':
            raise RuntimeError(f'Release v{version} is not newer than installed v{old}; bump VERSION before packaging')
        paths = sorted(list(meta['files']) + ['release.json'])
        ensure_regular_targets(root, paths)
        staged = git_staged_conflicts(root, paths)
        if staged:
            raise RuntimeError('Staged Git changes in release-managed files must be committed or unstaged before updating: '
                               + ', '.join(staged[:12]))
        conflicts = git_has_conflicts(root, paths)
        # Updater bootstrap may have been extracted first from this very release.
        # Do not treat identical staged files as user edits; keep rejecting any
        # *different* tracked source changes before overwriting them.
        conflicts = [name for name in conflicts
                     if not ((root / name).is_file() and (stage / name).is_file()
                             and hashlib.sha256((root / name).read_bytes()).digest()
                                == hashlib.sha256((stage / name).read_bytes()).digest())
                     and not still_matches_previous_release(root, name)]
        # Managed source edits are backed up, not discarded or silently merged.
        # This lets the release proceed while preserving the user's exact bytes.
        # The backup is created before ANY source file is replaced below.
        # Check service ownership before changing *any* existing code.
        preflight_service_ownership(root)
        wait_until_idle(root)
        # Exact back-up of overwritten source, including previously untracked files.
        backup = root / 'updates/.backups' / f'before-v{version}-{int(time.time())}'
        backup.mkdir(parents=True)
        originals = []
        for name in paths:
            target = root / name
            if target.is_file():
                dest = backup / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest)
                originals.append(name)
        (backup / 'original-files.json').write_text(json.dumps(originals))
        (backup / 'release-from.txt').write_text(old + '\n')
        (backup / 'local-edits.json').write_text(json.dumps({
            'release': version,
            'preservedTrackedEdits': sorted(conflicts),
            'restoreExample': 'cp "<backup>/README.md" "<repo>/README.md"',
        }, indent=2) + '\n')
        if conflicts:
            info('Preserved locally edited tracked files BEFORE replacement: ' + ', '.join(conflicts))
            info('Recovery copies: ' + str(backup))
        previous_was_running = managed_pid(root) is not None
        info(f'Upgrading v{old} → v{version}; backup: {backup}')
        try:
            copy_into_place(stage, root, paths)
            ensure_dependencies(root)
            stop_studio(root)
            start_studio(root, version)
        except Exception:
            info('Upgrade failed; restoring previous source…')
            # Stop only our own process; never kill unrelated listener.
            try: stop_studio(root)
            except Exception as e: info(f'Rollback service-stop warning: {e}')
            for name in paths:
                dest = root / name
                saved = backup / name
                if saved.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved, dest)
                else:
                    dest.unlink(missing_ok=True)
            if previous_was_running:
                try: start_studio(root, old)
                except Exception as e: info(f'Rollback restart FAILED: {e}')
            raise
        (state / 'installed-version').write_text(version + '\n')
        (state / 'last-backup').write_text(str(backup) + '\n')
        info('Local upgrade successful')
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('zip', type=Path)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    try:
        installed = install(args.zip.resolve(), args.repo.resolve(), args.verify_only)
        return 0
    except Exception as error:
        info('ERROR: ' + str(error))
        return 1


if __name__ == '__main__':
    sys.exit(main())
