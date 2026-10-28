#!/usr/bin/env python3
"""Optional isolated browser check for local-source and upload-picker controls.

Uses system Chromium with mocked API responses. No Flask server or external traffic.
"""
from pathlib import Path
from shutil import which
from playwright.sync_api import sync_playwright
import json

ROOT=Path(__file__).resolve().parents[1]
BROWSER=which('chromium') or which('google-chrome')
if not BROWSER: raise SystemExit('Chromium not installed')
markup=(ROOT/'core/templates/index.html').read_text()
markup=markup.replace('{% for p in presets %}<option value="{{p.filename}}">{{p.name}} · {{p.count}} clips</option>{% endfor %}', '<option value="extra.json">Extra · 1 clips</option>')
markup=markup.replace("{{ {'token':token,'presets':presets,'session':session,'workspace':workspace}|tojson }}",json.dumps({'token':'local','session':{},'workspace':'/tmp/test','presets':[]}))
markup=markup.replace('{{ blender }}','/usr/bin/true')
markup=markup.replace("{{ url_for('static', filename='studio.css') }}",'data:text/css,')
js=(ROOT/'core/static/studio.js').read_text()
markup=markup.replace('<script defer src="{{ url_for(\'static\', filename=\'studio.js\') }}"></script>', '<script>'+js+'</script>')
for filename in ['rantlist.js','release-watch.js']:
    markup=markup.replace('<script defer src="{{ url_for(\'static\', filename=\''+filename+'\') }}"></script>','')
    markup=markup.replace('<script src="{{ url_for(\'static\', filename=\''+filename+'\') }}" defer></script>','')
markup=markup.replace('<script type="module" src="{{ url_for(\'static\', filename=\'viewer.mjs\') }}"></script>','')
# Give the code a mocked viewer, gallery switch, and local Flask response. All
# body/selection checks happen in browser so hidden file inputs behave normally.
shim='''<script>
Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}}});
window.submittedForms=[];
window.MixamoViewer={load:async()=>{},getClips:()=>[],captureStage:async()=>null};
window.fetch=async (url,opts={})=>{
 const path=String(url).split('?')[0],method=opts.method||'GET';
 let data={};
 if(path==='/api/library') data={models:[
   {id:'aaaaaaaaaaaaaaaaaaaaaaaa',name:'Generated character',canExtend:true,clips:12,source:'generated',glbUrl:'/mock-glb',downloadUrl:'#'},
   {id:'bbbbbbbbbbbbbbbbbbbbbbbb',name:'Imported only',canExtend:false,clips:2,source:'imported',glbUrl:'/mock-glb',downloadUrl:'#'}]};
 else if(path==='/api/status') data={session:{portOpen:false},presets:[{name:'Extra',count:1,filename:'extra.json'}],job:null};
 else if(path==='/api/jobs'){
   const form=opts.body;
   window.submittedForms.push([...form.entries()].map(([key,val])=>[key,val instanceof File?val.name:val]));
   data={job:{id:'job1',status:'starting',phase:'Preparing',lines:[],logCursor:0},animations:13,extension:{reused:12,remaining:1}};
 }
 return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
};
window.addEventListener('DOMContentLoaded',()=>document.getElementById('galleryLocal').addEventListener('click',()=>{}));
</script>'''
markup=markup.replace('<script id="bootstrap"',shim+'<script id="bootstrap"')
assert '{{' not in markup and '{%' not in markup
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=BROWSER,headless=True,args=['--no-sandbox'])
    for mode in ('library','upload','imported'):
        page=browser.new_page(viewport={'width':1280,'height':870})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.set_content(markup,wait_until='load')
        page.evaluate('window.dispatchEvent(new Event("mixamo-viewer-ready"))')
        try: page.wait_for_function('document.getElementById("sourceLibraryName").textContent.includes("Generated character")',timeout=3000)
        except Exception:
            print('BROWSER ERRORS',errors)
            print('SOURCE',page.locator('#sourceLibraryName').inner_text())
            print('CARDS',page.locator('.model-card').count())
            print('BOOTSTRAP',page.locator('#bootstrap').inner_text()[:250]);raise
        assert page.locator('#characterPath').count()==0
        assert page.locator('#sourcePathButton').count()==0
        assert page.locator('#characterFile').evaluate('(el)=>el.hidden')
        assert page.locator('#sourceLibraryButton').get_attribute('aria-pressed')=='true'
        if mode=='library':
            page.click('#start')
            page.wait_for_function('window.submittedForms.length===1')
            form=dict(page.evaluate('window.submittedForms[0]'))
            assert form['source_mode']=='library' and form['library_id']=='aaaaaaaaaaaaaaaaaaaaaaaa',form
            assert 'character_file' not in form
        elif mode=='upload':
            with page.expect_file_chooser() as chooser: page.click('#sourceUploadButton')
            chooser.value.set_files({'name':'new-character.fbx','mimeType':'application/octet-stream','buffer':b'Kaydara FBX Binary'+bytes(60)})
            assert page.locator('#sourceUploadName').inner_text().startswith('New character: new-character.fbx')
            assert page.locator('#sourceUploadButton').get_attribute('aria-pressed')=='true'
            page.click('#start')
            page.wait_for_function('window.submittedForms.length===1')
            form=dict(page.evaluate('window.submittedForms[0]'))
            assert form['source_mode']=='upload' and form['character_file']=='new-character.fbx',form
        else:
            page.locator('.model-card-main').nth(1).click()
            assert 'cannot be extended' in page.locator('#sourceLibraryName').inner_text()
            page.click('#start')
            assert page.evaluate('window.submittedForms.length')==0
            assert 'no original source' in page.locator('#feedback').inner_text()
        assert not errors,(mode,errors)
        page.close()
    browser.close()
print('PASS: existing generated model, hidden single upload picker, imported-model rejection')
