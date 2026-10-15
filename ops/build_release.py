#!/usr/bin/env python3
"""Build a reproducible, digest-verified full Mixamo Actions update ZIP."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / 'VERSION').read_text().strip()
if not re.fullmatch(r'\d+\.\d+\.\d+', version): raise SystemExit('Invalid VERSION')
# Read release notes from the same Markdown that is pushed to Git.
log_text = (ROOT / 'updates-log.md').read_text(encoding='utf-8')
match = re.search(r'^## v' + re.escape(version) + r'[^\n]*\n(.*?)(?=^## |\Z)', log_text, re.M | re.S)
if not match: raise SystemExit('updates-log.md must contain a section for v' + version)
notes = [line[2:].strip() for line in match.group(1).splitlines() if line.startswith('- ')]
if not notes: raise SystemExit('Release section has no bullet points')
notes = notes[:8]
(ROOT / 'site' / 'release.json').write_text(
    json.dumps({'version':version,'changes':notes},ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
allowed_root = {'VERSION', 'updates-log.md', 'README.md', '.gitignore', 'mixamo-studio-watch.sh', 'mixamo-watch.env.example'}
excluded = {'.venv','.git','__pycache__','.DS_Store','node_modules','uploads','exports','.mixamo-updater','.state','.backups'}
paths = []
for p in ROOT.rglob('*'):
    rel=p.relative_to(ROOT)
    if not p.is_file() or any(seg in excluded for seg in rel.parts) or rel.name.endswith(('.pyc','.log','.glb','.fbx','.blend','.zip','.db','.sqlite','.sqlite3')): continue
    if rel.parts[0] in ('core','site','ops','tests') or str(rel) in allowed_root:
        paths.append(rel)
paths=sorted(paths,key=lambda x:str(x))
# Archive payloads are allowlisted rather than automatically including updates,
# source models, local browser profiles, credentials or other state.
checksums={str(name):hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}
manifest={'name':'mixamo-actions','version':version,'date':datetime.date.today().isoformat(),
          'changes':notes,'files':checksums}
(ROOT/'release.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
out=ROOT/'updates'/f'mixamo-actions-v{version}.zip';out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for name in paths+[Path('release.json')]:
        data=(ROOT/name).read_bytes(); item=zipfile.ZipInfo(str(name),date_time=(2026,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED
        item.external_attr=(0o100644 << 16)
        z.writestr(item,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
print(out)
