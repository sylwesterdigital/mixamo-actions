#!/usr/bin/env python3
"""Resolve a credential-free Git push URL without modifying Git configuration.

- HTTPS github.com origins become git@github.com:<owner>/<repo>.git on push.
- Existing SSH and local Git origins are kept intact.
- Explicit MIXAMO_GIT_PUSH_URL overrides the choice (for custom SSH remotes).
- Never reads, copies, or stores private keys, credentials, or tokens.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

GITHUB_HTTPS = re.compile(r'^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$', re.I)


def choose_push_url(origin: str, override: str = '') -> str:
    value = (override or origin).strip()
    if not value or any(char.isspace() for char in value):
        raise ValueError('Push URL is missing or contains whitespace')
    match = GITHUB_HTTPS.fullmatch(value)
    if match:
        return f'git@github.com:{match.group(1)}/{match.group(2)}.git'
    if re.match(r'^https?://', value, re.I):
        raise ValueError('Refusing interactive HTTPS push. Set MIXAMO_GIT_PUSH_URL to a trusted SSH remote.')
    if '://' in value and not value.startswith(('ssh://', 'file://')):
        raise ValueError('Unsupported push URL scheme')
    return value


def resolve_from_repo(repo: Path, override: str = '') -> str:
    if not override:
        origin = subprocess.check_output(['git', '-C', str(repo), 'remote', 'get-url', 'origin'], text=True).strip()
    else:
        origin = ''
    return choose_push_url(origin, override)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(resolve_from_repo(args.repo, os.getenv('MIXAMO_GIT_PUSH_URL', '')))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f'[mixamo-git] {exc}\n')

if __name__ == '__main__':
    main()
