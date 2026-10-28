"""Crash-safe Mixamo FBX checkpointing. No credentials or remote server calls.

An export is reusable only if its requested animation matches the saved plan,
its source/preset identity matches, and the on-disk FBX passes validation. The
legacy manifest can be imported once for jobs made before this checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

CHECKPOINT = '.mixamo-resume.json'


def valid_resume_command(command, *, executable: str, pipeline: Path,
                         character: Path, preset: Path, output: Path | None = None) -> bool:
    """Accept only commands written by the local Studio, including Python -u.

    Check the input paths against the SHA-verified saved job before launching a
    subprocess. Never pass unchecked arguments from the local recovery JSON to
    an executable. This is deliberately independent of Flask for regression tests.
    """
    if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
        return False
    script = str(pipeline)
    if command[:3] == [executable, '-u', script]:
        args = command[3:]
    elif command[:2] == [executable, script]:  # compatibility with older jobs
        args = command[2:]
    else:
        return False
    paired = {'--cdp', '--character', '--animations', '--blender', '--out',
              '--draco-level', '--webp-quality', '--manual-rig-timeout'}
    switches = {'--skip-download', '--skip-upload', '--confirm-upload',
                '--require-textures', '--no-draco', '--no-webp',
                '--continue-on-error', '--dry-run'}
    seen = {}
    i = 0
    while i < len(args):
        flag = args[i]
        if flag in seen or flag not in paired | switches:
            return False
        if flag in paired:
            if i + 1 >= len(args) or not args[i + 1] or args[i + 1].startswith('--'):
                return False
            seen[flag] = args[i + 1]
            i += 2
        else:
            seen[flag] = True
            i += 1
    return (seen.get('--character') == str(character) and
            seen.get('--animations') == str(preset) and
            (seen.get('--out') is None or (output is not None and seen['--out'] == str(output))))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def safe_filename(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')
    return value[:130] or 'animation'


def planned(specs: list[dict]) -> list[tuple[dict, str]]:
    used = set()
    result = []
    for spec in specs:
        label = str(spec.get('filename') or spec.get('title') or spec.get('search'))
        if spec.get('description') and not spec.get('filename'):
            label += ' - ' + str(spec['description'])
        name = safe_filename(label)
        root = name
        number = 2
        while name.casefold() in used:
            name = f'{root}-{number}'
            number += 1
        used.add(name.casefold())
        result.append((spec, name + '.fbx'))
    return result


def verify_fbx(path: Path) -> bool:
    """Reject HTML, empty/truncated downloads, partial and arbitrary .fbx files."""
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size < 256:
            return False
        with path.open('rb') as file:
            head = file.read(32)
        # Mixamo uses binary FBX; tolerate standard ASCII FBX for imports.
        return head.startswith(b'Kaydara FBX Binary  \x00\x1a\x00') or head.lstrip().startswith(b'; FBX')
    except OSError:
        return False


def write_atomic(path: Path, obj: dict) -> None:
    tmp = path.with_name(path.name + '.tmp')
    try:
        with tmp.open('w', encoding='utf-8') as file:
            json.dump(obj, file, indent=2, ensure_ascii=False)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class ResumePlan:
    def __init__(self, out: Path, specs: list[dict], *, source_sha256: str, preset_sha256: str):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.expected = planned(specs)
        self.source_sha256 = source_sha256
        self.preset_sha256 = preset_sha256
        self.path = self.out / CHECKPOINT
        self.entries: dict[str, dict] = {}
        existing = list(self.out.glob('*.fbx'))
        if self.path.is_file():
            info = json.loads(self.path.read_text(encoding='utf-8'))
            if info.get('schema') != 1 or info.get('source_sha256') != source_sha256 or \
                    info.get('preset_sha256') != preset_sha256 or \
                    info.get('requested') != [spec for spec, _ in self.expected]:
                raise ValueError('Existing downloads belong to a different character or animation preset. '
                                 'Use a different output folder; existing files were not modified.')
            self.entries = info.get('completed', {})
            if not isinstance(self.entries, dict):
                raise ValueError('Corrupt Mixamo resume checkpoint; existing exports were preserved.')
        elif existing:
            # v1.2.5 and earlier wrote a manifest containing exactly the specs
            # successfully downloaded. Only adopt files with matching records.
            old = self.out / 'manifest.json'
            try:
                previous = json.loads(old.read_text(encoding='utf-8'))
                records = previous['successful']
                evidence = {(row['file'], json.dumps(row['requested'], sort_keys=True)) for row in records}
            except (OSError, KeyError, TypeError, ValueError):
                evidence = set()
            matched = 0
            for spec, name in self.expected:
                file = self.out / name
                if file.exists() and (name, json.dumps(spec, sort_keys=True)) in evidence and verify_fbx(file):
                    self.entries[name] = self._entry(file, spec)
                    matched += 1
            unexpected = [p.name for p in existing if p.name not in self.entries]
            if unexpected:
                raise ValueError('Cannot safely reuse unverified legacy FBX files: ' + ', '.join(unexpected[:4]) +
                                 '. No files were removed. Move those files out of fbx/ and retry.')
            print(f'[resume] Adopted {matched} verified FBXs from the previous download manifest.', flush=True)
        self.save()

    def _entry(self, path: Path, spec: dict) -> dict:
        return dict(spec=spec, size=path.stat().st_size, sha256=digest(path),
                    saved=datetime.now(timezone.utc).isoformat())

    def save(self) -> None:
        write_atomic(self.path, dict(schema=1, source_sha256=self.source_sha256,
                                     preset_sha256=self.preset_sha256,
                                     requested=[spec for spec, _ in self.expected],
                                     completed=self.entries))

    def valid(self, spec: dict, name: str) -> bool:
        row = self.entries.get(name)
        path = self.out / name
        if not isinstance(row, dict) or row.get('spec') != spec or not verify_fbx(path):
            return False
        try:
            return row['size'] == path.stat().st_size and row['sha256'] == digest(path)
        except (KeyError, OSError):
            return False

    def record(self, spec: dict, name: str) -> None:
        file = self.out / name
        if not verify_fbx(file):
            raise ValueError(f'Invalid or incomplete FBX download: {name}')
        self.entries[name] = self._entry(file, spec)
        self.save()

    def completed(self) -> int:
        return sum(self.valid(spec, name) for spec, name in self.expected)

    def missing(self) -> list[str]:
        return [name for spec, name in self.expected if not self.valid(spec, name)]

    def ensure_no_untracked(self) -> None:
        expected = {name for _, name in self.expected}
        extra = [p.name for p in self.out.glob('*.fbx') if p.name not in expected]
        if extra:
            raise ValueError('FBX directory also contains unrelated clips: ' + ', '.join(extra[:5]) +
                             '. Keep different presets in different output folders.')
