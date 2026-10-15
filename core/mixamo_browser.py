#!/usr/bin/env python3
"""Mixamo batch exports via the visible UI. No private download API or cookie export.

Run: python3 mixamo_batch.py --character ./MyRig.zip --animations ./animations.json

Use --cdp with a dedicated Brave profile that you first sign into normally.
This avoids a Google sign-in attempt inside Playwright-controlled Chromium.
No browser cookies or passwords are exported.

Mixamo UI changes sometimes. This is a starting implementation tested for
Python syntax, NOT against an authenticated Mixamo account.
"""
from __future__ import annotations

import argparse
import os
import json
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import HTTPError, URLError

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

MIXAMO = "https://www.mixamo.com/"
DEFAULT_PROFILE = Path.home() / ".mixamo-playwright-profile"
MAX_FBX_SIZE = 1024 * 1024 * 1024  # reasonable safety limit when unpacking ZIP


def clean(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def safe_filename(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .")
    return (s[:130] or "animation")


def read_animations(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("animations")
    if not isinstance(data, list) or not data:
        raise ValueError("animations.json must contain a nonempty array or {\"animations\": [...]} object")
    result = []
    for item in data:
        spec = {"search": item} if isinstance(item, str) else item
        if not isinstance(spec, dict) or not (spec.get("search") or spec.get("title")):
            raise ValueError(f"Invalid animation entry: {item!r}")
        result.append(spec)
    return result


def prepare_character(path: Path, tempdir: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".fbx":
        return path.resolve()
    if path.suffix.lower() != ".zip":
        raise ValueError("Character input should be .fbx, or a .zip containing one rigged .fbx")
    with zipfile.ZipFile(path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir() and
                   Path(m.filename).suffix.lower() == ".fbx" and
                   not Path(m.filename).name.startswith("._") and
                   "__MACOSX" not in Path(m.filename).parts]
        if len(members) != 1:
            raise ValueError(f"ZIP contains {len(members)} FBX files; expected exactly one rigged FBX. "
                             "For OBJ+textures ZIPs, upload through Mixamo manually to complete auto-rigging.")
        member = members[0]
        if member.file_size > MAX_FBX_SIZE:
            raise ValueError("FBX inside ZIP exceeds 1 GiB safety limit")
        out = tempdir / safe_filename(Path(member.filename).name)
        with archive.open(member) as source, out.open("wb") as target:
            shutil.copyfileobj(source, target)
        if out.stat().st_size == 0:
            raise ValueError("FBX inside ZIP is empty")
        print(f"[character] Extracted {member.filename!r} -> {out}")
        return out


def resolve_cdp_endpoint(address: str) -> str:
    """Resolve an existing Brave CDP session to a browser WebSocket URL.

    Traditional remote debugging supplies /json/version. Some recent
    Chromium-based browsers' UI-enabled remote debugging serves only a
    WebSocket endpoint and returns HTTP 404 for that discovery URL.
    """
    if address.startswith(("ws://", "wss://")):
        from urllib.parse import urlsplit
        parts = urlsplit(address)
        if parts.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('Only a localhost Brave debugging WebSocket is allowed')
        print('[brave] Using supplied local WebSocket endpoint directly')
        return address
    if not address.startswith(("http://", "https://")):
        raise ValueError("--cdp expects http(s)://host:port or ws(s)://host:port/devtools/browser")

    from urllib.parse import urlsplit
    parsed = urlsplit(address)
    if not parsed.hostname or not parsed.port:
        raise ValueError("--cdp must include an explicit host and port")
    # Attach only to a local debugging port, never disclose the CDP socket.
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Use a localhost Brave CDP address, not a remotely exposed debugging port")
    discovery_url = address.rstrip("/") + "/json/version"
    opener = build_opener(ProxyHandler({}))  # Don't route localhost through HTTP proxies.
    try:
        request = Request(discovery_url, headers={"Accept": "application/json"})
        with opener.open(request, timeout=5) as response:
            details = json.load(response)
    except HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(f"Brave CDP discovery returned HTTP {exc.code}") from exc
        # Chromium's WebSocket-only remote-debugging mode may return 404
        # to both /json/version and /json/version/ yet still support CDP.
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        # Some Brave/Chromium builds write a browser-specific UUID in this file.
        profile = Path(os.environ.get('MIXAMO_BRAVE_PROFILE',
                                      str(Path.home() / '.mixamo-brave-profile'))).expanduser()
        devtools_file = profile / 'DevToolsActivePort'
        if devtools_file.is_file():
            contents = devtools_file.read_text(encoding='utf-8').splitlines()
            if len(contents) >= 2 and contents[0].strip() == str(parsed.port) \
                    and contents[1].startswith('/devtools/browser/'):
                print('[brave] HTTP discovery returned 404; using browser WebSocket path from DevToolsActivePort')
                return f'{ws_scheme}://{host}:{parsed.port}{contents[1].strip()}'
        print("[brave] HTTP discovery returned 404; trying WebSocket-only CDP")
        return f"{ws_scheme}://{host}:{parsed.port}/devtools/browser"
    except (URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(
            "Cannot contact Brave CDP. Verify Brave is running with remote "
            "debugging enabled and that the selected localhost port is correct."
        ) from exc

    if not isinstance(details, dict) or not details.get("webSocketDebuggerUrl"):
        raise RuntimeError("Brave CDP discovery returned no browser WebSocket URL")
    ws_url = details["webSocketDebuggerUrl"]
    if not isinstance(ws_url, str) or not ws_url.startswith(("ws://", "wss://")) \
            or "/devtools/browser/" not in ws_url:
        raise RuntimeError("Brave CDP discovery returned an unexpected browser WebSocket")
    print("[brave] Resolved browser WebSocket from CDP discovery")
    return ws_url


def ensure_login(page, *, via_cdp: bool = False):
    page.goto(MIXAMO, wait_until="domcontentloaded", timeout=60000)
    print("\n[login] Checking Mixamo session in the open browser...")
    try:
        page.locator(".editor-sidebar .sidebar-header button").first.wait_for(timeout=20000)
    except PWTimeout:
        if via_cdp:
            raise RuntimeError(
                "Mixamo isn't signed in or its UI didn't load. Stop this run. "
                "Use ./brave_session.sh login (without remote debugging), "
                "sign in through Google/Adobe, close that Brave window entirely, "
                "then run ./brave_session.sh automate and rerun this program. "
                "Do not attempt Google login in the controlled session."
            )
        input("[login] Sign in manually in the browser if prompted; press ENTER when ready ... ")
        page.locator(".editor-sidebar .sidebar-header button").first.wait_for(timeout=60000)


def upload_character(page, path: Path):
    print(f"[upload] Uploading {path.name}")
    button = page.locator(".editor-sidebar .sidebar-header button").filter(
        has_text=re.compile(r"^\s*Upload Character\s*$", re.I)).first
    button.wait_for(timeout=30000)

    # Mixamo may open a native file chooser directly or a dropzone dialog first.
    try:
        with page.expect_file_chooser(timeout=4000) as chooser:
            button.click()
        chooser.value.set_files(str(path))
        print("[upload] File passed to Mixamo via file chooser.")
        return
    except PWTimeout:
        pass

    inputs = page.locator('input[type="file"]')
    if inputs.count():
        inputs.last.set_input_files(str(path))
        print("[upload] File passed to Mixamo via file input.")
        return

    choose = page.get_by_role("button", name=re.compile(r"Browse|Choose File|Select.*File", re.I))
    if choose.count():
        try:
            with page.expect_file_chooser(timeout=5000) as chooser:
                choose.first.click()
            chooser.value.set_files(str(path))
            print("[upload] File passed to Mixamo via secondary chooser.")
            return
        except PWTimeout:
            pass

    raise RuntimeError("Could not locate Mixamo upload file chooser; use --confirm-upload after updating the selector")


def character_modal_state(page) -> dict:
    """Read ONLY visible Mixamo dialog controls; do not infer rigging from the editor behind it."""
    return page.evaluate(r"""() => {
      const visible = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      const modals = [...document.querySelectorAll('.modal, [role="dialog"]')]
        .filter(visible);
      const modal = modals.find(m => m.querySelector('.autorig-modal')) ||
        modals.find(m => m.querySelector('.modal-content')) || modals[0];
      const download = [...document.querySelectorAll('.editor-sidebar .sidebar-header button')]
        .find(el => /^Download$/i.test(el.textContent.trim()) && !el.disabled);
      const header = document.querySelector('.product-preview .product-nav h2')?.textContent.trim() || '';
      if (!modal) return {visible:false, editorReady:!!download, header};
      const step = modal.querySelector('.autorig-info h3')?.textContent.trim() || '';
      const title = modal.querySelector('.modal-title')?.textContent.trim() || '';
      const message = modal.querySelector('.autorig-info p')?.textContent.trim() || '';
      const button = [...modal.querySelectorAll('.modal-footer button')]
        .find(el => /^Next$/i.test(el.textContent.trim()) && visible(el));
      return {visible:true, autorigger:!!modal.querySelector('.autorig-modal'),
        step, title, message, nextEnabled:!!button && !button.disabled,
        editorReady:!!download, header};
    }""")


def rigging_notice(page, message: str):
    """Small, removable notice inside Brave, not a browser alert that would block clicks."""
    page.evaluate(r"""message => {
      let note = document.getElementById('mixamo-manual-rigging-notice');
      if (!note) {
        note = document.createElement('div');
        note.id = 'mixamo-manual-rigging-notice';
        note.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:2147483647;'+
          'max-width:410px;background:#172033;color:#fff;border:2px solid #ffad54;'+
          'padding:13px 16px;border-radius:10px;font:14px/1.5 sans-serif;'+
          'box-shadow:0 7px 26px #0008;pointer-events:none;';
        document.body.appendChild(note);
      }
      note.textContent = message;
    }""", message)


def remove_rigging_notice(page):
    try:
        page.evaluate("document.getElementById('mixamo-manual-rigging-notice')?.remove()")
    except Exception:
        pass


def wait_for_character_confirmation(page, *, automatic=False,
                                    manual_timeout=900, source_name=''):
    """Advance Mixamo's safe Review/confirmation buttons; stop at manual rigging screens.

    'Review' is the last stage even for some already-rigged FBX uploads. It is
    safe to click its Next when enabled. Orient and Place Markers need a human:
    never invent orientation or rig markers.
    """
    print('\n[character] Waiting for uploaded character and Mixamo confirmation...')
    if not automatic:
        print('[character] Manual confirmation mode: use Next in Brave; no terminal input is needed.', flush=True)

    start = time.monotonic()
    deadline = start + max(manual_timeout, 30)
    saw_modal = False
    saw_confirmation = False
    saw_manual = False
    manual_logged = False
    last_stage = ''
    previous_header = source_name
    stable_since = None
    try:
        while time.monotonic() < deadline:
            state = character_modal_state(page)
            step = clean(state.get('step'))
            title = clean(state.get('title'))
            msg = clean(state.get('message'))
            if state['visible']:
                saw_modal = True
                stable_since = None
                if state.get('autorigger'):
                    if 'error' in step or 'failed' in step or 'rigging failed' in msg:
                        raise RuntimeError(f'Mixamo Auto-Rigger reported an error: {state}')
                    if step in ('review', 'confirm', 'confirmation'):
                        # The screenshot supplied by the user demonstrates this precise
                        # Auto-Rigger -> Review -> Next state for a rigged FBX.
                        if not automatic:
                            saw_manual = True
                            if last_stage != step:
                                print('[ACTION REQUIRED] Auto-Rigger Review: click Next in Brave to confirm.', flush=True)
                                last_stage = step
                            rigging_notice(page, 'Review the rigged character, then click Next in Brave.')
                            page.wait_for_timeout(750)
                            continue
                        if state.get('nextEnabled'):
                            print('[character] Auto-Rigger Review ready: clicking Next automatically.')
                            btn = page.locator('.autorig-modal .modal-footer button.btn-primary').filter(
                                has_text=re.compile(r'^\s*Next\s*$', re.I)).first
                            btn.click(timeout=15000)
                            saw_confirmation = True
                            remove_rigging_notice(page)
                            page.wait_for_timeout(1300)
                        else:
                            page.wait_for_timeout(500)
                        continue
                    if (step.startswith('orient') or 'marker' in step or
                            'skeleton lod' in step or 'place markers' in msg):
                        saw_manual = True
                        label = state.get('step') or 'manual rigging'
                        if not manual_logged or last_stage != step:
                            print(f'[ACTION REQUIRED] Auto-Rigger: {label}. '
                                  'Complete orientation/markers/Next in the visible Brave window. '
                                  f'Timeout: {manual_timeout}s.', flush=True)
                            manual_logged = True
                        last_stage = step
                        rigging_notice(page, f'Mixamo needs manual rigging: {label}. '
                                             'Complete the Auto-Rigger steps in Brave; automation will resume.')
                        page.wait_for_timeout(750)
                        continue
                    if ('rigging' in step or 'rigging' in msg or 'wait' in step or
                            'uploading' in step or 'processing' in step):
                        if last_stage != step:
                            print(f'[character] Mixamo processing: {state.get("step") or state.get("message")}')
                            last_stage = step
                        page.wait_for_timeout(900)
                        continue
                    # Unknown Auto-Rigger step might require marker placement.
                    saw_manual = True
                    if last_stage != step:
                        print('[ACTION REQUIRED] Unrecognized Auto-Rigger stage: '
                              f'{state.get("step")!r}. Complete this stage manually.', flush=True)
                        last_stage = step
                    rigging_notice(page, 'Mixamo Auto-Rigger needs your input. '
                                         'Finish the visible steps; automation resumes afterward.')
                    page.wait_for_timeout(750)
                    continue

                # Some versions display a separate upload-success confirmation,
                # containing a single Next button. Never click other dialogs.
                confirmed_text = ' '.join((step, title, msg))
                if (state.get('nextEnabled') and any(x in confirmed_text for x in (
                    'character uploaded', 'upload complete', 'upload successful',
                    'review', 'rigged character', 'confirm your character'))):
                    if not automatic:
                        saw_manual = True
                        if last_stage != 'upload confirmation':
                            print('[ACTION REQUIRED] Confirm uploaded character: click Next in Brave.', flush=True)
                            last_stage = 'upload confirmation'
                        rigging_notice(page, 'Confirm the uploaded character by clicking Next in Brave.')
                        page.wait_for_timeout(750)
                        continue
                    print('[character] Clicking upload confirmation Next.')
                    page.locator('.modal:visible .modal-footer button.btn-primary').filter(
                        has_text=re.compile(r'^\s*Next\s*$', re.I)).first.click(timeout=15000)
                    saw_confirmation = True
                    page.wait_for_timeout(1100)
                    continue
                if 'error' in confirmed_text or 'failed' in confirmed_text:
                    raise RuntimeError(f'Mixamo rejected the uploaded character: {confirmed_text[:320]}')
                page.wait_for_timeout(750)
                continue

            # Wait until initial upload starts: the old editor may still be
            # visible behind the file picker before the new modal appears.
            if not saw_modal and not saw_confirmation:
                if state.get('header') and previous_header and state['header'] != previous_header:
                    saw_confirmation = True  # An immediate rigged upload changed the preview.
                else:
                    page.wait_for_timeout(600)
                    continue
            if state.get('editorReady'):
                if stable_since is None:
                    stable_since = time.monotonic()
                if time.monotonic() - stable_since >= 2.0:
                    remove_rigging_notice(page)
                    print('[character] Character editor ready; moving to animation downloads.')
                    return
            else:
                stable_since = None
            page.wait_for_timeout(500)
        detail = ('Manual Auto-Rigger has not been completed.' if saw_manual else
                  'Character confirmation did not finish or no modal was observed.')
        try:
            screenshot = Path.cwd() / 'mixamo_rigging_timeout.png'
            page.screenshot(path=str(screenshot))
            detail += f' Screenshot: {screenshot}'
        except Exception:
            pass
        raise RuntimeError(f'{detail} Timed out after {manual_timeout}s. '
                           'Complete rigging and retry using --skip-upload.')
    finally:
        remove_rigging_notice(page)


def matching_cards(cards: list[dict], spec: dict) -> list[dict]:
    """Find a requested variant without falling back to a different motion ID.

    A motionId is the decimal ID in the animation card's thumbnail URL,
    e.g. thumbnails/motions/124620901/animated.gif. It is a UI identifier,
    not a documented Mixamo API identifier.
    """
    motion_id = str(spec.get("motionId") or "").strip()
    desired_title = clean(spec.get("title"))
    desired_description = clean(spec.get("description"))
    requested = clean(spec.get("search") or spec.get("title"))
    candidates = []
    for card in cards:
        title = clean(card["title"])
        description = clean(card["description"])
        if motion_id and card["motionId"] != motion_id:
            continue
        if desired_title and title != desired_title:
            continue
        if desired_description and description != desired_description:
            continue
        if not motion_id and not desired_title and not desired_description:
            # Backward-compatible best-effort matches for simple strings.
            score = 0 if title == requested else 1 if title.startswith(requested) else 2 if requested in title else 3 if requested in description else 99
            if score == 99:
                continue
        else:
            score = 0
        candidates.append({**card, "score": score})
    return sorted(candidates, key=lambda c: (c["score"], c["page"], c["index"]))


def choose_result(page, spec: dict) -> dict:
    query = str(spec.get("search") or spec.get("title") or "").strip()
    if not query:
        raise ValueError("Animation requires a search query or title")

    # Search all result pages, not only the first one: several animations
    # share titles such as 'Jump', 'Walking', and 'Idle'.
    def navigate(page_number: int, expected_start: int | None = None):
        hash_url = f"#/?page={page_number}&query={quote(query)}&type=Motion%2CMotionPack"
        page.evaluate("hash => { window.location.hash = hash; }", hash_url)
        page.wait_for_function(
            r"""params => {
              const hash = new URLSearchParams(location.hash.split('?')[1] || '');
              if (Number(hash.get('page')) !== params.page || hash.get('query') !== params.query) return false;
              const tag = [...document.querySelectorAll('.product-list .tag-list .tag')]
                .some(el => el.textContent.toLowerCase().includes('"' + params.query.toLowerCase() + '"'));
              if (!tag) return false;
              const text = document.querySelector('.product-list .search-description')?.textContent || '';
              const match = text.match(/Showing\s+(\d+)\s*[-–]\s*(\d+)\s+of\s+([\d,]+)\s+results/i);
              const single = text.match(/Showing\s+([\d,]+)\s+results/i);
              if (!match && !single) return false;
              return params.start === null || (match ? Number(match[1]) : 1) === params.start;
            }""",
            arg={"page": page_number, "query": query, "start": expected_start},
            timeout=45000,
        )
        return page.evaluate(r"""() => {
          const text = document.querySelector('.product-list .search-description')?.textContent || '';
          const match = text.match(/Showing\s+(\d+)\s*[-–]\s*(\d+)\s+of\s+([\d,]+)\s+results/i);
          const single = text.match(/Showing\s+([\d,]+)\s+results/i);
          if (match) return {start:Number(match[1]), end:Number(match[2]),
            total:Number(match[3].replace(/,/g,''))};
          if (single) return {start:1, end:Number(single[1].replace(/,/g,'')),
            total:Number(single[1].replace(/,/g,''))};
          return null;
        }""")

    info = navigate(1, 1)
    if not info:
        raise RuntimeError(f"Mixamo search did not finish loading: {query!r}")
    page_size = max(1, info["end"] - info["start"] + 1)
    pages = min(50, (info["total"] + page_size - 1) // page_size)
    all_cards = []
    for current in range(1, pages + 1):
        if current > 1:
            navigate(current, (current - 1) * page_size + 1)
        results = page.evaluate(r"""() =>
          [...document.querySelectorAll('.product-list .product.product-animation')]
            .map((card, index) => {
              const title = (card.querySelector('.product-info > p')?.textContent || '').trim();
              const description = (card.querySelector('.product-metadata li')?.textContent || '')
                .replace(/^\s*Description:\s*/i, '').trim();
              const thumbnail = card.querySelector('.product-image img')?.getAttribute('src') || '';
              const id = thumbnail.match(/\/thumbnails\/motions\/(\d+)\//);
              return {index, title, description, thumbnail, motionId:id?.[1] || ''};
            })
        """)
        all_cards.extend({**card, "page": current} for card in results)
        # An exact motion-ID match can stop scanning early, once the
        # additional title/description constraints have also been verified.
        if matching_cards(all_cards, spec) and (
            spec.get("motionId") or not spec.get("description")
        ):
            # An exact motion-ID match is definitive; for legacy simple-string
            # requests retain first-page selection instead of crawling all pages.
            break

    matches = matching_cards(all_cards, spec)
    if not matches:
        same_title = [c for c in all_cards if clean(c["title"]) == clean(spec.get("title") or query)]
        examples = "; ".join(f"{c['title']} — {c['description']} (motionId={c['motionId']})"
                             for c in same_title[:8])
        raise ValueError(f"No EXACT Mixamo match for {spec!r} in {pages} result page(s). "
                         f"Available examples: {examples or '(none)'}. "
                         "The script will not substitute another animation.")
    if (spec.get("motionId") or spec.get("description")) and len(matches) > 1:
        raise ValueError(f"Multiple cards match the specified variant: {matches}. "
                         "Add a unique motionId to animations.json.")
    if len(matches) > 1:
        print(f"[warning] {len(matches)} Mixamo cards match {query!r}; "
              f"defaulting to {matches[0]['title']!r} — {matches[0]['description']!r} "
              f"(motionId={matches[0]['motionId']}). Set motionId to choose precisely.")
    result = matches[0]
    # In the absence of a motion-ID, searching every page may leave the UI on
    # another page. Navigate back to the chosen card's page before clicking.
    if result["page"] != current:
        navigate(result["page"], (result["page"] - 1) * page_size + 1)
    locator = page.locator('.product-list .product.product-animation').nth(result['index'])
    # Verify the actual thumbnail on this page before selecting.
    actual_id = locator.locator('.product-image img').get_attribute('src') or ''
    if result['motionId'] and f"/motions/{result['motionId']}/" not in actual_id:
        raise RuntimeError('Mixamo results changed while selecting the card; refusing an incorrect animation')
    locator.click()
    # Wait for React to mark this specific thumbnail as selected. Merely
    # waiting for the title is insufficient when several cards are 'Jump'.
    if result['motionId']:
        page.wait_for_function(
            """id => [...document.querySelectorAll('.product-list .product.product-animation.product-selected')]
                .some(card => (card.querySelector('.product-image img')?.getAttribute('src') || '')
                       .includes('/motions/' + id + '/'))""",
            arg=result['motionId'], timeout=45000,
        )
    page.locator('.animation-settings-header h3').filter(
        has_text=re.compile('^' + re.escape(result['title']) + '$', re.I)).first.wait_for(timeout=60000)
    page.wait_for_timeout(750)
    return result


def set_in_place(page, spec: dict, default=True) -> str:
    if not spec.get("inPlace", default):
        return "disabled by configuration"
    checkbox = page.locator(
        '.editor-sidebar .animation-settings-list input[type="checkbox"][name="inplace"]'
    )
    if not checkbox.count():
        return "not offered"
    if not checkbox.first.is_checked():
        checkbox.first.check(timeout=10000)
        page.wait_for_timeout(1200)
    if not checkbox.first.is_checked():
        raise RuntimeError("Mixamo In Place checkbox did not stay checked")
    return "enabled"


def open_download_modal(page):
    button = page.locator(".editor-sidebar .sidebar-header button").filter(
        has_text=re.compile(r"^\s*Download\s*$", re.I)).first
    button.click(timeout=15000)
    modal = page.locator('.modal:visible, [role="dialog"]:visible').filter(
        has_text=re.compile("Download Settings", re.I)).first
    modal.wait_for(timeout=30000)
    return modal


def set_modal_option(page, category: str, value: str):
    # Native select controls are found by the options they contain rather than
    # relying on changing React component IDs or select order.
    modal = page.locator('.modal:visible, [role="dialog"]:visible').filter(
        has_text=re.compile("Download Settings", re.I)).first
    candidates = modal.locator("select")
    for i in range(candidates.count()):
        select = candidates.nth(i)
        choices = select.evaluate("""el => [...el.options].map(o => ({
          label:o.textContent.trim(), value:o.value
        }))""")
        labels = [clean(x["label"]) for x in choices]
        if category == "format" and not any("fbx binary" in x for x in labels):
            continue
        if category == "skin" and not ("with skin" in labels and "without skin" in labels):
            continue
        if category == "fps" and not any(x == "30" or x == "30 fps" for x in labels):
            continue
        if category == "reduction" and not ("none" in labels and "with skin" not in labels):
            continue
        for choice in choices:
            s = clean(choice["label"])
            if (category == "format" and "fbx binary" in s or
                category == "skin" and s == clean(value) or
                category == "fps" and s in (value, value + " fps") or
                category == "reduction" and s == clean(value)):
                select.select_option(value=choice["value"], timeout=10000)
                page.wait_for_timeout(150)
                return
        raise RuntimeError(f"Download dialog has no option {category}={value!r}")
    raise RuntimeError(f"Download dialog {category} select not found")


def download_one(page, outpath: Path, spec: dict):
    modal = open_download_modal(page)
    set_modal_option(page, "format", "fbx binary")
    set_modal_option(page, "skin", "with skin")
    set_modal_option(page, "fps", "30")
    set_modal_option(page, "reduction", "none")
    modal = page.locator('.modal:visible, [role="dialog"]:visible').filter(
        has_text=re.compile("Download Settings", re.I)).first
    confirm = modal.get_by_role("button", name=re.compile(r"^\s*Download\s*$", re.I)).first
    # This waits for a real browser download event. save_as waits until done.
    try:
        with page.expect_download(timeout=300000) as pending:
            confirm.click(timeout=20000)
        download = pending.value
    except PWTimeout as exc:
        # A timeout means Mixamo did not trigger a Playwright download event.
        # Do not click Download twice: the first request might still complete.
        # Capture local, actionable diagnostics without storing cookies or URLs.
        try:
            status = page.evaluate('''() => ({
              modal: [...document.querySelectorAll('.modal, [role="dialog"]')]
                .filter(x => x.getClientRects().length).map(x => x.innerText.slice(0,350)).slice(0,2),
              alerts: [...document.querySelectorAll('[role="alert"], .toast, .notification')]
                .filter(x => x.getClientRects().length).map(x => x.innerText.slice(0,160)).slice(0,3),
              action: document.querySelector('.animation-settings-header h3')?.textContent?.trim() || ''
            })''')
            print('[download-diag] Mixamo UI after timeout: '+json.dumps(status,ensure_ascii=False), flush=True)
        except Exception as diag_exc:
            print('[download-diag] Could not read dialog state: '+type(diag_exc).__name__, flush=True)
        try:
            screenshot = outpath.with_suffix('.download-timeout.png')
            page.screenshot(path=str(screenshot), timeout=10000)
            print('[download-diag] Local browser screenshot: '+str(screenshot),flush=True)
        except Exception:
            pass
        raise RuntimeError('Mixamo did not emit a browser download event within 300 seconds. '
                           'Check Brave Downloads and the Mixamo dialog; see [download-diag] '
                           'in Logs. Re-run the job to resume existing FBXs.') from exc
    if not download.suggested_filename.lower().endswith(".fbx"):
        raise RuntimeError(f"Unexpected downloaded file: {download.suggested_filename}")
    download.save_as(str(outpath))  # BLOCKS until the actual FBX transfer completes
    if download.failure():
        raise RuntimeError(f"Browser download failed: {download.failure()}")
    if not outpath.is_file() or outpath.stat().st_size == 0:
        raise RuntimeError("Downloaded FBX is missing or empty")
    return download.suggested_filename


def make_zip(outdir: Path, archive_path: Path, manifest: dict):
    files = sorted(x for x in outdir.glob("*.fbx") if x.stat().st_size > 0)
    if not files:
        print("[zip] No completed FBX files; no ZIP created")
        return
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in files:
            z.write(file, arcname=file.name)
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[zip] Created: {archive_path} ({len(files)} FBX files)")


def run():
    parser = argparse.ArgumentParser(description="Export Mixamo animations using Playwright, then zip completed FBX files")
    parser.add_argument("--character", type=Path, help="Your rigged .fbx or ZIP containing exactly one rigged FBX")
    parser.add_argument("--animations", type=Path, default=Path(__file__).with_name("animations.json"))
    parser.add_argument("--out", type=Path, default=Path.cwd() / "mixamo_exports")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE,
                        help="Dedicated Playwright Chromium profile (ignored when --cdp is used)")
    parser.add_argument("--cdp", nargs="?", const="http://127.0.0.1:9222", default=None,
                        metavar="URL", help="Attach to already-running Brave using Chrome DevTools Protocol; "
                        "default endpoint: http://127.0.0.1:9222")
    parser.add_argument("--skip-upload", action="store_true", help="Use current Mixamo character without uploading")
    parser.add_argument("--auto-confirm-character", action="store_true", help="Wait for the editor instead of prompting at upload")
    parser.add_argument("--continue-on-error", action="store_true", help="Skip failed animations and continue")
    parser.add_argument("--manual-rig-timeout", type=int, default=900,
                        help="Seconds to allow user to manually orient/place markers if Mixamo auto-rigging is needed")
    args = parser.parse_args()

    specs = read_animations(args.animations)
    if not args.skip_upload and args.character is None:
        parser.error("Provide --character rigged.fbx or rigged.zip, or use --skip-upload")
    args.out.mkdir(parents=True, exist_ok=True)
    archive_path = args.out.parent / (args.out.name + ".zip")
    manifest_path = args.out / "manifest.json"
    successes, failures = [], []
    used_names = set()

    with tempfile.TemporaryDirectory(prefix="mixamo-character-") as temp:
        character = prepare_character(args.character, Path(temp)) if not args.skip_upload else None
        with sync_playwright() as playwright:
            cdp_browser = None
            if args.cdp:
                print(f"[brave] Connecting to existing Brave session at {args.cdp}")
                ws_endpoint = resolve_cdp_endpoint(args.cdp)
                try:
                    cdp_browser = playwright.chromium.connect_over_cdp(ws_endpoint, timeout=20000)
                except Exception as ex:
                    raise RuntimeError(
                        "Cannot attach to Brave CDP. If HTTP discovery returned 404, "
                        "your Brave version may require the browser-specific WebSocket "
                        "path from the local DevToolsActivePort file. Check that Brave "
                        "is still open and the debugging port belongs to the intended "
                        "profile. Original error: " + str(ex)
                    ) from ex
                if not cdp_browser.contexts:
                    raise RuntimeError("Attached Brave exposes no default browser context")
                browser = cdp_browser.contexts[0]
                print("[brave] Attached to the open, signed-in Brave profile")
            else:
                browser = playwright.chromium.launch_persistent_context(
                    str(args.profile.expanduser()), headless=False,
                    accept_downloads=True, viewport={"width": 1512, "height": 982},
                )
            browser.set_default_timeout(20000)
            page = next((p for p in browser.pages if "mixamo.com" in p.url), None) or browser.new_page()
            def report_failed_response(response):
                try:
                    if response.status >= 400 and 'mixamo.com' in response.url:
                        from urllib.parse import urlsplit
                        address = urlsplit(response.url)
                        # Never log query parameters, cookie values, or credentials.
                        print(f'[mixamo-http] {response.status} {response.request.method} '
                              f'{address.netloc}{address.path[:140]}', flush=True)
                except Exception: pass
            page.on('response', report_failed_response)
            try:
                ensure_login(page, via_cdp=bool(args.cdp))
                previous_character_name = page.locator('.product-preview .product-nav h2').first.text_content(timeout=3000) or ''
                if character:
                    upload_character(page, character)
                    wait_for_character_confirmation(
                        page, automatic=args.auto_confirm_character,
                        manual_timeout=args.manual_rig_timeout,
                        source_name=previous_character_name.strip())
                else:
                    # --skip-upload: no new character, so no upload dialog to confirm.
                    page.locator('.editor-sidebar .sidebar-header button').filter(
                        has_text=re.compile(r'^\s*Download\s*$', re.I)).first.wait_for(timeout=30000)
                for n, spec in enumerate(specs, start=1):
                    label = str(spec.get("filename") or spec.get("title") or spec.get("search"))
                    if spec.get("description") and not spec.get("filename"):
                        label += " - " + str(spec["description"])
                    basename = safe_filename(label)
                    original_name = basename
                    suffix = 2
                    while basename.casefold() in used_names:
                        basename = f"{original_name}-{suffix}"
                        suffix += 1
                    used_names.add(basename.casefold())
                    target = args.out / (basename + ".fbx")
                    print(f"\n[{n}/{len(specs)}] {label}")
                    force = bool(spec.get("redownload", False))
                    if target.is_file() and target.stat().st_size > 0 and not force:
                        print(f"[skip] Already downloaded: {target.name}")
                        successes.append({"requested": spec, "file": target.name, "status": "already present"})
                        continue
                    if force and target.exists():
                        # Quarantine the older animation so even --continue-on-error
                        # never imports the incorrect old FBX into the combined GLB.
                        previous = args.out / '.replaced'
                        previous.mkdir(exist_ok=True)
                        backup = previous / (target.name + '.old')
                        target.replace(backup)
                        print(f"[replace] Old file moved aside: {backup}")
                    try:
                        chosen = choose_result(page, spec)
                        in_place = set_in_place(page, spec)
                        print(f"[match] {chosen['title']} — {chosen['description']} "
                              f"(motionId={chosen['motionId']}) | In Place: {in_place}")
                        source_name = download_one(page, target, spec)
                        print(f"[saved] {target} ({target.stat().st_size:,} bytes)")
                        successes.append({"requested": spec, "matched": chosen,
                                          "inPlace": in_place, "sourceFilename": source_name,
                                          "file": target.name, "status": "downloaded"})
                    except Exception as ex:
                        print(f"[ERROR] {type(ex).__name__}: {ex}", file=sys.stderr)
                        if target.exists() and target.stat().st_size == 0:
                            target.unlink()
                        failures.append({"requested": spec, "error": f"{type(ex).__name__}: {ex}"})
                        try:
                            page.locator('.modal:visible button').filter(
                                has_text=re.compile(r"^\s*(Cancel|Close)\s*$", re.I)).first.click(timeout=2000)
                        except Exception:
                            pass
                        if not args.continue_on_error:
                            print("[stop] Fix the issue and rerun to resume; completed FBXs will be skipped")
                            break
            finally:
                manifest = {"successful": successes, "failed": failures,
                            "note": "Exports use the Mixamo site UI; individual animations may vary."}
                manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
                make_zip(args.out, archive_path, manifest)
                if cdp_browser is not None:
                    # Disconnect CDP; do not destroy the dedicated Brave profile.
                    cdp_browser.close()
                else:
                    browser.close()
    print(f"\nFinished: {len(successes)} successful, {len(failures)} failed. ZIP: {archive_path if archive_path.exists() else '(none)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
