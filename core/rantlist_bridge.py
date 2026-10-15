"""Local-only Rantlist Stage bridge (uses Rantlist r630's unmodified authenticated API).

IMPORTANT: A Rantlist portable profile UUID is an account identity credential under
Rantlist's existing `hello` protocol. Never persist an imported profile, UUID,
WebSocket capability, or owner-only model URL on disk or in browser storage.
An Rantlist account permits only one active WebSocket for a nickname: connecting
here can replace that account's current Rantlist tab session.
"""
from __future__ import annotations

import json
import re
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

RANTLIST_HTTPS = 'https://rantlist.me'
RANTLIST_WS = 'wss://rantlist.me/ws'
MAX_MODEL = 20 * 1024 * 1024
MAX_PREVIEW = 192 * 1024
ASSET_ID = re.compile(r'[a-f0-9]{32}\Z', re.I)
VIEW_PATH = re.compile(r'/stage-private/view/[a-f0-9]{32}(?:\.(?:glb|png|jpg|jpeg|webp)|/thumb\.(?:png|jpg|jpeg|webp))\Z', re.I)

class RantlistError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def parse_portable_profile(document: object) -> dict:
    if not isinstance(document, dict) or document.get('format') != 'rantlist-profile' or document.get('version') != 1:
        raise RantlistError('Select a Rantlist profile export (format rantlist-profile, version 1).')
    identity, profile = document.get('identity'), document.get('profile')
    if not isinstance(identity, dict) or not isinstance(profile, dict):
        raise RantlistError('Profile identity or details are missing.')
    uid = identity.get('id') or identity.get('uuid')
    if not isinstance(uid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', uid):
        raise RantlistError('Profile identity is missing or invalid.')
    if identity.get('uuid') is not None and identity['uuid'] != uid:
        raise RantlistError('Profile UUID does not match identity ID.')
    nickname = profile.get('nickname')
    if not isinstance(nickname, str) or not re.fullmatch(r'[\w. -]{2,24}', nickname, re.UNICODE):
        raise RantlistError('Profile nickname is missing or invalid.')
    # Mirror Rantlist's own profileToNetwork() field mapping. Rantlist r630
    # persists the complete metadata on sign-in, so omitting existing fields
    # could erase the account's avatar, links or visibility settings.
    metadata = {'profileVisibility':'public' if profile.get('publicProfile') is True else 'private', 'client':'browser'}
    for field, length in [('status',100), ('bio',280), ('email',120), ('phone',40),
                          ('website',240), ('linkedin',240), ('github',240),
                          ('instagram',240), ('x',240), ('color',7), ('avatar3d',240)]:
        value = profile.get(field)
        if isinstance(value, str) and len(value) <= length:
            if field == 'color' and not re.fullmatch(r'#[A-Fa-f0-9]{6}', value):
                continue
            if field == 'avatar3d' and value and not re.fullmatch(r'/avatar-3d/[A-Fa-f0-9-]{36}(?:-mixamo)?\.glb(?:\?v=\d+)?', value):
                continue
            metadata[field] = value
    avatar = profile.get('avatar')
    if isinstance(avatar, str) and len(avatar) <= 72*1024 and re.fullmatch(r'data:image/(?:jpeg|png|gif|webp);base64,[A-Za-z0-9+/]+={0,2}',avatar):
        metadata['avatar'] = avatar
    scale = profile.get('uiScale')
    if isinstance(scale, (int,float)) and not isinstance(scale,bool) and 50 <= scale <= 200:
        metadata['uiScale'] = int(scale)
    return {'identityId': uid, 'nickname': nickname.strip(), 'metadata': metadata}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RantlistError('Rantlist unexpectedly redirected a private gallery request.', 502)


class RantlistBridge:
    """One explicit, ephemeral owner session for this single-user localhost Studio."""
    def __init__(self):
        self.lock = threading.RLock()
        self.ws = None
        self.token = None
        self.expiry = 0
        self.nickname = None
        self.identity_id = None
        self.error = None
        self.session_generation = 0
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        self._catalog_cache = None
        self._catalog_expires = 0

    def close(self):
        with self.lock:
            ws = self.ws
            self.session_generation += 1
            self.ws = None
            self.token = None
            self.expiry = 0
            self.nickname = None
            self.identity_id = None
            self.error = None
            self._catalog_cache = None
            self._catalog_expires = 0
        if ws is not None:
            try: ws.close()
            except Exception: pass

    def status(self) -> dict:
        with self.lock:
            valid = self.ws is not None and self.token is not None and self.expiry > time.time() * 1000 + 10_000
            return {'connected': bool(valid), 'nickname': self.nickname if valid else None,
                    'expiresAt': self.expiry if valid else None,
                    'error': self.error}

    def _public_versions(self) -> dict:
        # Rantlist r630 requires browser UI + protocol versions on the *WebSocket
        # upgrade URL* (not in hello). Source: server.js parseClientVersion() and
        # enforceClientVersion(); the same public /version endpoint is used by its UI.
        req = Request(RANTLIST_HTTPS + '/version', headers={
            'Accept': 'application/json', 'Cache-Control': 'no-store'})
        try:
            with self.opener.open(req, timeout=10) as response:
                data = response.read(4097)
        except RantlistError:
            raise
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            raise RantlistError('Cannot read Rantlist public UI version; connection was not attempted.', 502) from exc
        if len(data) > 4096:
            raise RantlistError('Rantlist version response is unexpectedly large.', 502)
        try:
            versions = json.loads(data)
        except (TypeError, ValueError) as exc:
            raise RantlistError('Rantlist returned invalid public UI version JSON.', 502) from exc
        if not isinstance(versions, dict):
            raise RantlistError('Rantlist returned invalid public UI version information.', 502)
        protocol = versions.get('protocolVersion')
        ui_version = versions.get('uiVersion')
        ui_hash = versions.get('uiHash')
        if (type(protocol) is not int or not 1 <= protocol <= 999999
                or not isinstance(ui_version, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', ui_version)
                or (ui_hash is not None and (not isinstance(ui_hash, str)
                     or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', ui_hash)))):
            raise RantlistError('Rantlist public UI version fields are invalid.', 502)
        return {'uiVersion': ui_version, 'protocolVersion': protocol, 'uiHash': ui_hash}

    @staticmethod
    def _versioned_ws_url(versions: dict) -> str:
        # Only controlled, validated fields from https://rantlist.me/version.
        params = {'uiVersion': versions['uiVersion'],
                  'protocolVersion': str(versions['protocolVersion']),
                  'reloadSupport': '1'}
        if versions.get('uiHash'):
            params['uiHash'] = versions['uiHash']
        return RANTLIST_WS + '?' + urlencode(params)

    def connect(self, profile: dict, *, socket_factory=None, version_fetcher=None):
        self.close()
        ws = None
        try:
            if socket_factory is None:
                import websocket  # websocket-client, not websockets
                socket_factory = lambda url: websocket.create_connection(url, timeout=15, suppress_origin=True)
            if version_fetcher is None:
                version_fetcher = self._public_versions
            # A deployment between /version and /ws can reject the first attempt.
            # Refresh the public version *once* without looping on auth failures.
            for attempt in range(2):
                versions = version_fetcher()
                ws = socket_factory(self._versioned_ws_url(versions))
                # The identity credential is sent only after the secure WS upgrade.
                ws.send(json.dumps({'type': 'hello', **profile}, separators=(',', ':')))
                got_hello = False
                version_changed = False
                deadline = time.monotonic() + 22
                while time.monotonic() < deadline:
                    try:
                        packet = json.loads(ws.recv())
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(packet, dict):
                        continue
                    if packet.get('type') == 'hello.ok':
                        actual = packet.get('user') or {}
                        if actual.get('identityId') != profile['identityId']:
                            raise RantlistError('Rantlist returned a different identity.', 403)
                        got_hello = True
                        ws.send('{"type":"stage.asset.authorize"}')
                    elif packet.get('type') == 'stage.asset.access' and got_hello:
                        token = packet.get('token')
                        if not isinstance(token, str) or not re.fullmatch('[a-fA-F0-9]{64}', token):
                            raise RantlistError('Rantlist returned an invalid Stage access capability.', 502)
                        if packet.get('identityId') != profile['identityId']:
                            raise RantlistError('Stage access belongs to a different identity.', 403)
                        expiry = float(packet.get('expiresAt') or 0)
                        if expiry < time.time()*1000 + 30_000:
                            raise RantlistError('Rantlist Stage access expired immediately.', 502)
                        with self.lock:
                            self.ws, self.token, self.expiry = ws, token, expiry
                            self.nickname, self.identity_id = profile['nickname'], profile['identityId']
                            generation = self.session_generation
                        ws.settimeout(8)
                        threading.Thread(target=self._reader, args=(ws, generation), daemon=True).start()
                        return self.status()
                    elif packet.get('type') == 'error':
                        if packet.get('code') == 'client_update_required':
                            version_changed = True
                            break
                        raise RantlistError('Rantlist refused sign-in: ' + str(packet.get('message') or packet.get('code') or 'Access denied')[:180], 403)
                if version_changed and attempt == 0:
                    ws.close()
                    ws = None
                    continue
                if version_changed:
                    raise RantlistError('Rantlist UI versions changed during login. Retry profile import.', 502)
                raise RantlistError('Timed out waiting for Rantlist Stage gallery authorization.', 504)
        except Exception as exc:
            if ws is not None:
                try: ws.close()
                except Exception: pass
            if isinstance(exc, RantlistError):
                raise
            raise RantlistError('Could not establish a secure Rantlist session: ' + type(exc).__name__, 502) from exc

    def _reader(self, ws, generation):
        # websocket-client auto-replies to WebSocket PING frames while recv runs.
        # Keep the socket open: Rantlist invalidates capabilities when it closes.
        last_refresh = 0
        try:
            while True:
                with self.lock:
                    if self.ws is not ws or self.session_generation != generation:
                        return
                    if self.expiry < time.time()*1000 + 5*60*1000 and time.monotonic()-last_refresh > 45:
                        ws.send('{"type":"stage.asset.authorize"}')
                        last_refresh = time.monotonic()
                try:
                    raw = ws.recv()
                    if not raw:
                        break
                    payload = json.loads(raw)
                    if payload.get('type') == 'stage.asset.access':
                        token, exp = payload.get('token'), float(payload.get('expiresAt') or 0)
                        with self.lock:
                            if self.ws is ws and payload.get('identityId') == self.identity_id and isinstance(token, str) and re.fullmatch('[a-fA-F0-9]{64}', token) and exp > time.time()*1000:
                                self.token, self.expiry = token, exp
                except ValueError:
                    continue
                except TimeoutError:
                    continue
                except Exception as exc:
                    if exc.__class__.__name__ in ('WebSocketTimeoutException', 'TimeoutError'):
                        continue
                    break
        finally:
            with self.lock:
                if self.ws is ws and self.session_generation == generation:
                    self.ws, self.token, self.expiry, self.identity_id = None, None, 0, None
                    self.error = 'Rantlist connection closed. Import your profile again to reconnect.'
                    self.nickname = None

    def _http(self, path: str, *, method='GET', data=None, media_type=None, max_bytes=MAX_MODEL+65536):
        if not path.startswith('/') or path.startswith('//') or urlsplit(path).scheme or urlsplit(path).netloc:
            raise RantlistError('Invalid Rantlist gallery path.', 400)
        with self.lock:
            if not self.ws or not self.token or self.expiry <= time.time()*1000+10_000:
                raise RantlistError('Rantlist session expired. Reconnect your profile.', 401)
            bearer = self.token
        headers = {'Authorization': 'Bearer '+bearer, 'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = media_type or 'application/octet-stream'
            headers['Content-Length'] = str(len(data))
        req = Request(RANTLIST_HTTPS + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=35) as response:
                content = response.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise RantlistError('Rantlist asset exceeded its maximum size.', 413)
                return content, response.headers.get('Content-Type', '')
        except HTTPError as exc:
            try: info = json.loads(exc.read(8192)); msg = str(info.get('error') or info.get('code') or 'Rantlist rejected the request')[:240]
            except (ValueError, TypeError): msg = 'Rantlist rejected the request'
            raise RantlistError(msg, exc.code if 400 <= exc.code < 500 else 502) from exc
        except (OSError, URLError) as exc:
            raise RantlistError('Rantlist is currently unreachable over HTTPS.', 502) from exc

    def _json(self, path, **options):
        data, _ = self._http(path, max_bytes=1024*1024, **options)
        try: return json.loads(data)
        except ValueError: raise RantlistError('Rantlist returned invalid gallery JSON.', 502)

    def _catalog(self):
        # A single private catalogue request serves many thumbnail cards; avoid
        # 60+ repeated list requests to the shared Rantlist server.
        with self.lock:
            if self._catalog_cache is not None and time.monotonic() < self._catalog_expires:
                return self._catalog_cache
        result = self._json('/stage-private/api/assets')
        with self.lock:
            self._catalog_cache, self._catalog_expires = result, time.monotonic() + 12
        return result

    def _invalidate_catalog(self):
        with self.lock:
            self._catalog_cache, self._catalog_expires = None, 0

    def list_assets(self):
        self._invalidate_catalog()  # Manual refresh should see fresh uploads.
        result = self._catalog()
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            raise RantlistError('Rantlist returned an unexpected gallery response.', 502)
        items = []
        for value in result['items'][:60]:
            if not isinstance(value, dict) or not ASSET_ID.fullmatch(str(value.get('id',''))): continue
            if value.get('kind') not in ('avatar', 'model') or value.get('ext') != 'glb': continue
            items.append({'id':value['id'], 'kind':value['kind'], 'name':str(value.get('name') or 'Avatar')[:80],
                          'size':int(value.get('size') or 0), 'updatedAt':value.get('updatedAt'),
                          'thumbnail':bool(value.get('thumbnailUrl'))})
        return {'items':items, 'storage':result.get('storage'), 'maxItems':result.get('maxItems',60)}

    def _asset_path(self, asset_id, which):
        if not ASSET_ID.fullmatch(str(asset_id)): raise RantlistError('Invalid Rantlist model ID.')
        listing = self._catalog()
        row = next((x for x in listing.get('items',[]) if x.get('id')==asset_id and x.get('kind') in ('avatar','model') and x.get('ext')=='glb'),None)
        if not row: raise RantlistError('Model is no longer in this profile gallery.', 404)
        path = row.get('modelUrl') if which=='glb' else row.get('thumbnailUrl')
        if not isinstance(path, str): raise RantlistError('No remote thumbnail available.', 404)
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or not VIEW_PATH.fullmatch(parsed.path):
            raise RantlistError('Rantlist returned an unsafe asset URL.', 502)
        if not re.fullmatch(r'k=[a-fA-F0-9]{64}&v=\d+', parsed.query):
            raise RantlistError('Rantlist asset capability is invalid.', 502)
        return path

    def asset(self, asset_id, which):
        path = self._asset_path(asset_id, which)
        return self._http(path, max_bytes=(MAX_MODEL+1024 if which=='glb' else MAX_PREVIEW+1024))

    def publish(self, *, glb: bytes, name: str, kind: str, thumbnail: bytes | None = None):
        if kind not in ('avatar','model'): raise RantlistError('Choose Avatar or Model gallery.')
        if not 20 <= len(glb) <= MAX_MODEL: raise RantlistError('Rantlist accepts GLBs up to 20 MiB.', 413)
        if not isinstance(name, str) or not name.strip(): raise RantlistError('Model name is required.')
        qs = urlencode({'kind':kind,'ext':'glb','name':name.strip()[:80], 'size':str(len(glb))})
        result = self._json('/stage-private/api/assets?'+qs, method='POST', data=glb, media_type='model/gltf-binary')
        self._invalidate_catalog()
        item = result.get('item') if isinstance(result,dict) else None
        if not isinstance(item,dict) or not ASSET_ID.fullmatch(str(item.get('id',''))):
            raise RantlistError('Rantlist upload response was incomplete; check your gallery before retrying.', 502)
        preview_saved = False
        preview_error = None
        if thumbnail and len(thumbnail) <= MAX_PREVIEW and thumbnail[:4] == b'RIFF' and thumbnail[8:12] == b'WEBP':
            try:
                p = f"/stage-private/api/assets/{item['id']}/thumbnail?" + urlencode({'v': str(item['updatedAt']), 'size':str(len(thumbnail))})
                self._json(p, method='POST', data=thumbnail, media_type='image/webp')
                preview_saved = True
            except RantlistError as exc:
                preview_error = str(exc)[:160]  # GLB remains published; report thumbnail problem.
        elif thumbnail:
            preview_error = 'Preview exceeds 192 KiB or is not a WebP image.'
        return {'id':item['id'], 'name':item.get('name',name), 'kind':kind, 'thumbnailSaved':preview_saved, 'thumbnailError':preview_error}

    def delete(self, asset_id):
        if not ASSET_ID.fullmatch(str(asset_id)): raise RantlistError('Invalid Rantlist model ID.')
        self._json('/stage-private/api/assets/'+asset_id, method='DELETE')
        self._invalidate_catalog()
        return {'ok':True}
