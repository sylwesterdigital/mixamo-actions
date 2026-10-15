"""Offline contract/security tests derived from Rantlist r630 server.js Stage API."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rantlist_bridge import RantlistBridge, RantlistError, parse_portable_profile, RANTLIST_HTTPS, RANTLIST_WS, NoRedirect

IDENTITY='10293847-abcd-4dee-9898-cd1848190101'
VERSIONS = {'uiVersion':'9.6.602', 'protocolVersion':70, 'uiHash':'0123456789abcdef'}
PROFILE = {'format':'rantlist-profile','version':1,'identity':{'id':IDENTITY,'uuid':IDENTITY},
    'profile':{'nickname':'AvatarMaker','color':'#ffdd00','publicProfile':True,
               'avatar3d':'/avatar-3d/10293847-abcd-4dee-9898-cd1848190101.glb?v=123',
               'email':'','avatar':'data:image/jpeg;base64,/9j/4AAQSkZJRg=='}}


class Socket:
    def __init__(self, identity=IDENTITY):
        self.sent=[]
        self.messages=[{'type':'welcome'}, {'type':'hello.ok','user':{'identityId':identity}},
            {'type':'stage.asset.access','identityId':identity, 'token':'f'*64,'expiresAt':9999999999999}]
    def send(self, message): self.sent.append(json.loads(message))
    def recv(self): return json.dumps(self.messages.pop(0)) if self.messages else ''
    def settimeout(self,n): self.timeout=n
    def close(self): pass


class RantlistContractTests(unittest.TestCase):
    def test_profile_import_follows_rantlist_profile_to_network(self):
        info=parse_portable_profile(PROFILE)
        self.assertEqual(info['identityId'],IDENTITY)
        self.assertEqual(info['metadata']['profileVisibility'],'public')
        self.assertEqual(info['metadata']['avatar'],PROFILE['profile']['avatar'])
        self.assertEqual(info['metadata']['avatar3d'],PROFILE['profile']['avatar3d'])
        self.assertNotIn('exportedAt',info)

    def test_profile_rejects_forged_mismatch_and_wrong_format(self):
        with self.assertRaisesRegex(RantlistError,'UUID'):
            parse_portable_profile({**PROFILE,'identity':{'id':IDENTITY,'uuid':'other-identity'}})
        with self.assertRaisesRegex(RantlistError,'format'):
            parse_portable_profile({'format':'other','version':1})
        with self.assertRaisesRegex(RantlistError,'nickname'):
            parse_portable_profile({**PROFILE,'profile':{'nickname':' '}})

    def test_session_issues_actual_rantlist_hello_and_authorize(self):
        bridge=RantlistBridge(); sock=Socket()
        with patch('rantlist_bridge.threading.Thread'):
            status=bridge.connect(parse_portable_profile(PROFILE),socket_factory=lambda url:sock,version_fetcher=lambda:VERSIONS)
        self.assertTrue(status['connected'])
        self.assertEqual(sock.sent[0]['type'],'hello')
        self.assertEqual(sock.sent[0]['identityId'],IDENTITY)
        self.assertEqual(sock.sent[1],{'type':'stage.asset.authorize'})
        self.assertEqual(bridge.token,'f'*64)
        bridge.close()
        self.assertFalse(bridge.status()['connected'])
        self.assertIsNone(bridge.token)

    def test_websocket_handshake_uses_public_rantlist_ui_protocol_and_hash(self):
        from urllib.parse import urlsplit, parse_qs
        versions = dict(VERSIONS)
        sock = Socket()
        urls = []
        def connect(url):
            urls.append(url)
            return sock
        with patch('rantlist_bridge.threading.Thread'):
            bridge = RantlistBridge()
            bridge.connect(parse_portable_profile(PROFILE), socket_factory=connect, version_fetcher=lambda:versions)
        u = urlsplit(urls[0])
        self.assertEqual(u.scheme, 'wss')
        self.assertEqual(u.hostname, 'rantlist.me')
        self.assertEqual(u.path, '/ws')
        self.assertEqual(parse_qs(u.query), {k:[v] for k,v in {
            'uiVersion':'9.6.602','protocolVersion':'70',
            'uiHash':'0123456789abcdef','reloadSupport':'1'}.items()})
        self.assertEqual(sock.sent[0]['type'], 'hello')
        bridge.close()

    def test_fetches_live_public_version_before_sending_identity(self):
        from io import BytesIO
        bridge = RantlistBridge()
        called = []
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return json.dumps(VERSIONS).encode()
        def open_request(req, timeout=None):
            called.append((req.full_url,timeout,req.headers))
            return Response()
        bridge.opener.open = open_request
        versions = bridge._public_versions()
        self.assertEqual(versions,VERSIONS)
        self.assertEqual(called[0][0],'https://rantlist.me/version')
        self.assertEqual(called[0][1],10)
        self.assertIn('Cache-control', called[0][2])

    def test_refuses_invalid_public_version_without_websocket_or_credentials(self):
        from urllib.error import URLError
        from unittest.mock import Mock
        bridge = RantlistBridge()
        for raw in (b'bad-json', b'{}', b'{"uiVersion":"/bad","protocolVersion":70}',
                    b'{"uiVersion":"ok","protocolVersion":0}',
                    b'{"uiVersion":"ok","protocolVersion":70,"uiHash":" a b"}',
                    b'x'*4097):
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,n):return raw
            bridge.opener.open = lambda req,timeout=None: Response()
            connect = Mock()
            with self.subTest(raw=raw[:35]), self.assertRaises(RantlistError):
                bridge.connect(parse_portable_profile(PROFILE),socket_factory=connect)
            connect.assert_not_called()
        bridge.opener.open = lambda req,timeout=None: (_ for _ in ()).throw(URLError('offline'))
        with self.assertRaisesRegex(RantlistError, 'public UI version'):
            bridge.connect(parse_portable_profile(PROFILE),socket_factory=Mock())

    def test_retries_client_version_mismatch_once_without_retrying_identity_denial(self):
        class Rejected(Socket):
            def __init__(self, code):
                super().__init__()
                self.messages=[{'type':'welcome'}, {'type':'error','code':code,'message':'Rejected'}]
        urls=[]
        sockets=[Rejected('client_update_required'),Socket()]
        bridge=RantlistBridge()
        with patch('rantlist_bridge.threading.Thread'):
            bridge.connect(parse_portable_profile(PROFILE),
                socket_factory=lambda url:(urls.append(url) or sockets.pop(0)),
                version_fetcher=lambda:VERSIONS)
        self.assertEqual(len(urls),2)
        bridge.close()
        denial=Mock(side_effect=[Rejected('nickname_in_use')])
        with self.assertRaisesRegex(RantlistError,'Rejected'):
            bridge.connect(parse_portable_profile(PROFILE),socket_factory=lambda url:denial(),
                version_fetcher=lambda:VERSIONS)
        self.assertEqual(denial.call_count,1)

    def test_websocket_handshake_matches_rantlist_r630_server_contract(self):
        import os
        upstream = os.environ.get('RANTLIST_SERVER_SOURCE')
        if not upstream:self.skipTest('Optional upstream source: set RANTLIST_SERVER_SOURCE')
        source=Path(upstream)
        if not source.is_file():self.skipTest('Rantlist source not found')
        text=source.read_text()
        for piece in ('function parseClientVersion(searchParams)',
                      "searchParams.get('uiVersion')", "searchParams.get('protocolVersion')",
                      "searchParams.get('uiHash')", "searchParams.get('reloadSupport')",
                      "requestUrl.pathname === '/version'"):
            self.assertIn(piece,text)

    def test_denies_mismatched_identity(self):
        bridge=RantlistBridge()
        with self.assertRaisesRegex(RantlistError,'different identity'):
            bridge.connect(parse_portable_profile(PROFILE),socket_factory=lambda url:Socket('another-identity'),version_fetcher=lambda:VERSIONS)
        self.assertFalse(bridge.status()['connected'])

    def test_listing_removes_private_capability_urls(self):
        bridge=RantlistBridge()
        asset={'id':'a'*32,'kind':'avatar','name':'My dancer','ext':'glb','size':3200,
               'modelUrl':'/stage-private/view/'+ 'a'*32 + '.glb?k='+'f'*64+'&v=12',
               'thumbnailUrl':'/stage-private/view/'+ 'a'*32 + '/thumb.webp?k='+'f'*64+'&v=12'}
        bridge._json=lambda *args,**kwargs:{'items':[asset]}
        data=bridge.list_assets()
        self.assertEqual(data['items'][0]['name'],'My dancer')
        self.assertNotIn('modelUrl',data['items'][0])
        self.assertNotIn('thumbnailUrl',data['items'][0])
        self.assertTrue(data['items'][0]['thumbnail'])
        self.assertEqual(bridge._asset_path('a'*32,'glb'),asset['modelUrl'])
        self.assertEqual(bridge._asset_path('a'*32,'thumbnail'),asset['thumbnailUrl'])

    def test_rejects_external_or_malformed_asset_urls(self):
        bridge=RantlistBridge(); id='a'*32
        for bad in ['https://evil.example/a.glb', '//evil.example/a.glb',
                    '/stage-private/view/'+id+'.glb?k=BAD',
                    '/stage-private/view/'+id+'.glb?k='+'b'*64+'&v=123&redirect=https://evil.example',
                    '/stage-private/view/../../api/secret?k='+'b'*64+'&v=1']:
            bridge._json=lambda *args,**kwargs:{'items':[{'id':id,'kind':'avatar','ext':'glb','modelUrl':bad}]}
            with self.subTest(path=bad),self.assertRaises(RantlistError):bridge._asset_path(id,'glb')
        self.assertEqual(RANTLIST_HTTPS,'https://rantlist.me')
        self.assertEqual(RANTLIST_WS,'wss://rantlist.me/ws')

    def test_publish_uses_rantlist_raw_glb_api_and_saves_optional_preview(self):
        bridge=RantlistBridge(); calls=[]
        def fake(path, **kw):
            calls.append((path,kw))
            if '/thumbnail?' in path:return {'item':{'id':'a'*32}}
            return {'item':{'id':'a'*32,'name':'Dancer','updatedAt':123}}
        bridge._json=fake
        preview=b'RIFF'+b'\0'*4+b'WEBP'+b'a'*60
        result=bridge.publish(glb=b'glTF'+b'a'*100,kind='avatar',name='Dancer',thumbnail=preview)
        self.assertTrue(result['thumbnailSaved']);self.assertIn('kind=avatar',calls[0][0]);self.assertIn('ext=glb',calls[0][0]);
        self.assertEqual(calls[0][1]['data'][:4],b'glTF');self.assertEqual(calls[1][1]['media_type'],'image/webp')

    def test_upload_rejects_oversized_and_unexpected_kinds(self):
        bridge=RantlistBridge()
        with self.assertRaisesRegex(RantlistError,'20 MiB'):
            bridge.publish(glb=b'x'*(20*1048576+1),kind='avatar',name='Over')
        with self.assertRaisesRegex(RantlistError,'Avatar or Model'):
            bridge.publish(glb=b'glTF'+b'x'*30,kind='floor',name='Wrong')

if __name__=='__main__':unittest.main()
