/* Mixamo Studio controller: isolated from Three.js so pipeline remains functional offline. */
(() => {
'use strict';
const init = JSON.parse(document.getElementById('bootstrap').textContent);
const TOKEN = init.token;
const $ = id => document.getElementById(id);
let sourceMode = 'library', presetMode = 'saved', cursor = 0, jobID = null;
let logArr = [], lastAutoPreview = null, activeJob = null, updatePending = false;
let libraryModels=[], librarySelection=null, openedLocalFile=null, libraryExpanded=true;
const getViewer = () => window.MixamoViewer;
const gallerySizes={s:112,m:164,xl:228};
const galleryRatios={square:'1 / 1',portrait:'2 / 3',landscape:'3 / 2'};
let gallerySize='m',galleryRatio='portrait';
try{
  const prefs=JSON.parse(localStorage.getItem('mixamo-gallery-layout')||'{}');
  if(Object.hasOwn(gallerySizes,prefs.size))gallerySize=prefs.size;
  if(Object.hasOwn(galleryRatios,prefs.ratio))galleryRatio=prefs.ratio;
}catch{}
function setGalleryLayout(size=gallerySize,ratio=galleryRatio){
  if(!Object.hasOwn(gallerySizes,size)||!Object.hasOwn(galleryRatios,ratio))return;
  gallerySize=size;galleryRatio=ratio;
  const dock=$('libraryDock');
  dock.dataset.gallerySize=size;
  dock.style.setProperty('--card-width',gallerySizes[size]+'px');
  dock.style.setProperty('--card-ratio',galleryRatios[ratio]);
  for(const b of document.querySelectorAll('[data-gallery-size]')){b.classList.toggle('selected',b.dataset.gallerySize===size);b.setAttribute('aria-pressed',String(b.dataset.gallerySize===size));}
  for(const b of document.querySelectorAll('[data-gallery-ratio]')){b.classList.toggle('selected',b.dataset.galleryRatio===ratio);b.setAttribute('aria-pressed',String(b.dataset.galleryRatio===ratio));}
  try{localStorage.setItem('mixamo-gallery-layout',JSON.stringify({size,ratio}));}catch{}
}
for(const b of document.querySelectorAll('[data-gallery-size]'))b.onclick=()=>setGalleryLayout(b.dataset.gallerySize,galleryRatio);
for(const b of document.querySelectorAll('[data-gallery-ratio]'))b.onclick=()=>setGalleryLayout(gallerySize,b.dataset.galleryRatio);
setGalleryLayout();
const storeKey = 'mixamo-studio-config-v1';
const fields = ['presetPathInput','blender','draco','webp','timeout','port'];
const checks = {skip_upload:'skipUpload',skip_download:'skipDownload',confirm_upload:'confirmUpload',require_textures:'requireTextures',no_draco:'noDraco',no_webp:'noWebp',continue_on_error:'continueOnError',dry_run:'dryRun'};
function setMode(type, mode) {
  const isSource = type === 'source'; if(isSource) sourceMode = mode; else presetMode = mode;
  const modes = isSource ? ['upload','library'] : ['path','saved'];
  for (const kind of modes){
    $(type+kind[0].toUpperCase()+kind.slice(1)).classList.toggle('hidden', kind!==mode);
    $(type+kind[0].toUpperCase()+kind.slice(1)+'Button').classList.toggle('selected',kind===mode);
    $(type+kind[0].toUpperCase()+kind.slice(1)+'Button').setAttribute('aria-pressed',String(kind===mode));
  }
  storeSettings();
}
// The single upload button opens a native picker; the file input is never shown.
// Do not enter upload mode until a file has actually been chosen.
$('sourceUploadButton').onclick=()=>$('characterFile').click();
$('characterFile').addEventListener('change',()=>{
  const file=$('characterFile').files?.[0];
  if(!file)return;
  if(!/\.(zip|fbx)$/i.test(file.name)||!file.size){
    $('characterFile').value='';feedback('Choose a nonempty character ZIP or FBX file.');return;
  }
  $('sourceUploadName').textContent=`New character: ${file.name}. Ready to build.`;
  setMode('source','upload');
  feedback(`Selected ${file.name} for a new character build.`,true);
});
$('sourceLibraryButton').onclick=()=>{setMode('source','library');updateSourceLibraryName();};
$('sourcePickModel').onclick=()=>{
  $('galleryLocal').click();setLibraryExpanded(true);
  const selected=$('libraryCards').querySelector('.model-card.selected');
  selected?.scrollIntoView({block:'nearest',inline:'nearest'});
  if(!librarySelection)showViewerNotice('Click a previously generated model in your Local Library to add more animations.');
};
$('presetPathButton').onclick = () => setMode('preset','path');
$('presetSavedButton').onclick = () => setMode('preset','saved');
for(const button of document.querySelectorAll('.sidebar-tabs .tab')) button.onclick=()=>openTab(button.dataset.tab);
function openTab(tab){for(const b of document.querySelectorAll('.sidebar-tabs .tab'))b.classList.toggle('active',b.dataset.tab===tab);$('tab-pipeline').classList.toggle('hidden',tab!=='pipeline');$('tab-activity').classList.toggle('hidden',tab!=='activity');}
$('toggleSidebar').onclick=()=>{if(window.matchMedia('(max-width:860px)').matches)$('sidebar').classList.toggle('mobile-open');else document.querySelector('.workspace').classList.toggle('sidebar-collapsed');};
function storeSettings(){
  const s={sourceMode,presetMode,fields:{},checks:{},preset:$('presetSelect').value};
  for(const f of fields) s.fields[f]=$(f).value;
  for(const id of Object.values(checks))s.checks[id]=$(id).checked;
  try{localStorage.setItem(storeKey,JSON.stringify(s));}catch{}
}
try{
  const state=JSON.parse(localStorage.getItem(storeKey)||'{}');
  if(state.fields)for(const [key,value] of Object.entries(state.fields))if($(key))$(key).value=value;
  if(state.checks)for(const [key,value]of Object.entries(state.checks))if($(key))$(key).checked=!!value;
  if(state.preset && Array.from($('presetSelect').options).some(o=>o.value===state.preset))$('presetSelect').value=state.preset;
  setMode('source',state.sourceMode==='upload' && $('characterFile').files?.length?'upload':'library');
  setMode('preset',state.presetMode==='path'?'path':'saved');
}catch{}
for(const id of [...fields,...Object.values(checks),'presetSelect'])$(id).addEventListener('change',storeSettings);
async function send(url,opts={}) {
  const result=await fetch(url,{...opts,headers:{...(opts.headers||{}),'X-Local-Token':TOKEN}});
  if(result.status>=400)window.MixamoDiagnostics?.record(opts.method||'GET',url,result.status);
  let data; try{data=await result.json();}catch{throw new Error(`Unexpected server response (${result.status})`);}
  if(!result.ok)throw new Error(data.error||`HTTP ${result.status}`);
  return data;
}
function feedback(message,good=false){
  $('feedback').replaceChildren();if(!message)return;
  const d=document.createElement('div');d.className=good?'done':'error';d.textContent=message;$('feedback').appendChild(d);
  if(!good)showViewerNotice(message,true);
}
function showViewerNotice(msg,isError=false){const el=$('viewerNotice');el.textContent=msg;el.classList.remove('hidden');el.classList.toggle('bad',isError);}
function dismissViewerNotice(){ $('viewerNotice').classList.add('hidden'); }
window.MixamoStudioNotice={show:showViewerNotice,dismiss:dismissViewerNotice};
for(const mode of ['login','automate']){
  $('brave'+(mode==='login'?'Login':'Automate')).onclick=async()=>{
    try{let r=await send('/api/brave/'+mode,{method:'POST'});feedback(r.message,true);showViewerNotice(r.message);}catch(e){feedback(e.message);}
  };
}
function refreshPresets(items){
  const list=$('presetSelect'),selected=list.value;
  list.replaceChildren(new Option('Select a motion preset…',''));
  for(const p of items) list.add(new Option(`${p.name} · ${p.count} clips`,p.filename));
  if(Array.from(list.options).some(o=>o.value===selected)) list.value=selected;
  else try{const st=JSON.parse(localStorage.getItem(storeKey)||'{}');if(st.preset)list.value=st.preset;}catch{}
}
// Local collection editor. The Mixamo collector remains the source of exact motion IDs.
let editorEntries=[], editorOriginal=null, editorDigest=null;
const editor=$('presetEditor');
function renderEditorEntries(){
  const list=$('presetEditList');list.replaceChildren();
  editorEntries.forEach((entry,index)=>{
    const row=document.createElement('div');row.className='preset-edit-item';
    const title=document.createElement('span');
    title.textContent=(typeof entry==='string'?entry:entry.title||entry.search||'Motion')+
      (entry.motionId?' · '+entry.motionId:'');
    const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.title='Remove this action';
    remove.onclick=()=>{editorEntries.splice(index,1);renderEditorEntries();};
    row.append(title,remove);list.append(row);
  });
  $('presetEditorStatus').textContent=`${editorEntries.length} actions in this collection`;
}
function resetEditor(){
  editorEntries=[];editorOriginal=null;editorDigest=null;
  $('editPresetName').value='';
  renderEditorEntries();editor.showModal();
}
$('presetNew').onclick=resetEditor;
$('presetEdit').onclick=async()=>{
  const selected=$('presetSelect').value;
  if(!selected)return feedback('Select a collection to edit, or click New collection.');
  try{
    const data=await send('/api/presets/'+encodeURIComponent(selected));
    editorOriginal=data.filename;editorDigest=data.sha256;
    const content=data.content;
    editorEntries=structuredClone(Array.isArray(content)?content:content.animations);
    $('editPresetName').value=Array.isArray(content)?selected.replace(/\.json$/i,''):(content.presetName||selected.replace(/\.json$/i,''));
    renderEditorEntries();editor.showModal();
  }catch(e){feedback(e.message);}
};
$('presetEditorClose').onclick=$('presetEditorCancel').onclick=()=>editor.close();
$('presetAddAction').onclick=()=>{
  const search=$('actionSearch').value.trim(),title=$('actionTitle').value.trim();
  const motionId=$('actionMotionId').value.trim(),description=$('actionDescription').value.trim();
  if(!search && !title){$('presetEditorStatus').textContent='Enter a search term or title.';return;}
  if(motionId && !/^\d{4,20}$/.test(motionId)){$('presetEditorStatus').textContent='Motion ID must be numeric.';return;}
  const entry={search:search||title,title:title||search};
  if(description)entry.description=description;
  if(motionId){entry.motionId=motionId;entry.filename=(title||search).replace(/[^a-z0-9 _-]/gi,'').trim()+'__'+motionId;}
  if(editorEntries.some(e=>e.motionId && e.motionId===motionId && motionId)){
    $('presetEditorStatus').textContent='This motion ID is already in the collection.';return;
  }
  editorEntries.push(entry);
  for(const id of ['actionSearch','actionTitle','actionDescription','actionMotionId'])$(id).value='';
  renderEditorEntries();
};
$('presetEditorSave').onclick=async()=>{
  const button=$('presetEditorSave');button.disabled=true;
  try{
    const data=await send('/api/presets/edit',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:$('editPresetName').value,animations:editorEntries,original:editorOriginal,sha256:editorDigest})});
    refreshPresets(data.presets);setMode('preset','saved');$('presetSelect').value=data.filename;
    storeSettings();editor.close();feedback(`Saved ${data.filename} · ${data.count} motions`,true);
  }catch(e){$('presetEditorStatus').textContent=e.message;}
  finally{button.disabled=false;}
};
window.MixamoStudioSceneSource={remote(){librarySelection=null;rememberLibrarySelection();renderLibrary();}};
function updateSourceLibraryName(){
  const m=libraryModels.find(item=>item.id===librarySelection);
  $('sourceLibraryName').textContent=m?
    (m.canExtend?`Selected: ${m.name} · ${m.clips??'?'} existing clips. Pick a motion collection and Build to add missing actions.`:
      (m.source==='optimized' ? `Selected: ${m.name}. This is a texture-optimized copy; choose the original generated model to extend its animations.` :
      `Selected: ${m.name}. This GLB was imported without its original rig and cannot be extended. Choose a generated model.`)):
    'Select a previously generated model from your Local Model Library below. No ZIP upload is required.';
  $('sourceLibraryName').classList.toggle('source-unavailable',!!m&&!m.canExtend);
}
let presetImportBusy=false, lastPresetImportAt=0;
$('presetFile').addEventListener('change',async()=>{
  const input=$('presetFile'),file=input.files?.[0];
  if(!file)return;
  if(presetImportBusy)return;
  const status=$('presetImportStatus');
  if(!/\.json$/i.test(file.name)){
    const message='Choose an animation .json file.';
    status.textContent=message;feedback(message);input.value='';return;
  }
  presetImportBusy=true;
  const wasStartDisabled=$('start').disabled;
  $('start').disabled=true;
  status.textContent=`Importing ${file.name}…`;
  try{
    const data=new FormData();data.set('file',file,file.name);
    const response=await send('/api/presets',{method:'POST',body:data});
    refreshPresets(response.presets);
    setMode('preset','saved');
    $('presetSelect').value=response.filename;
    lastPresetImportAt=Date.now();
    storeSettings();
    const message=`${response.alreadySaved?'Already saved':'Imported'}: ${response.filename} · ${response.count} animations. Selected for the next build.`;
    status.textContent=message;feedback(message,true);
  }catch(e){
    status.textContent=`Import failed: ${e.message}`;
    feedback(`Animation JSON import failed: ${e.message}`);
  }finally{
    input.value='';presetImportBusy=false;$('start').disabled=wasStartDisabled;
  }
});
function buildForm(){
  const d=new FormData();d.set('source_mode',sourceMode);d.set('preset_mode',presetMode);
  if(sourceMode==='upload' && $('characterFile').files[0])d.set('character_file',$('characterFile').files[0]);
  else if(sourceMode==='library')d.set('library_id',librarySelection||'');
  if(presetMode==='saved')d.set('preset',$('presetSelect').value);else d.set('preset_path',$('presetPathInput').value.trim());
  for(const id of ['draco','webp','timeout','port','blender'])d.set(id,$(id).value);
  for(const [f,id]of Object.entries(checks))d.set(f,$(id).checked?'true':'false');
  return d;
}
$('start').onclick=async()=>{
  if(presetImportBusy)return feedback('Wait until the animation JSON import finishes.');
  if(sourceMode==='library'){
    const selected=libraryModels.find(m=>m.id===librarySelection);
    if(!selected)return feedback('Select a previously generated model in the Local Model Library first.');
    if(!selected.canExtend)return feedback('This imported GLB has no original source. Select a generated model instead.');
  }else if(!$('characterFile').files?.[0]){
    return feedback('Choose a character ZIP or FBX with Upload new ZIP / FBX.');
  }
  feedback('');storeSettings();$('start').disabled=true;
  try{const r=await send('/api/jobs',{method:'POST',body:buildForm()});cursor=0;logArr=[];jobID=r.job.id;lastAutoPreview=null;showViewerNotice(r.extension?`Extending model: ${r.extension.reused} existing FBXs reused, ${r.extension.remaining} additional clips needed`:`Build started · ${r.animations} animations`);renderJob(r.job);}
  catch(e){feedback(e.message);$('start').disabled=false;}
};
$('resumeBuild').onclick=async()=>{
  feedback('');$('resumeBuild').disabled=true;
  try{
    const r=await send('/api/jobs/resume',{method:'POST'});
    cursor=0;logArr=[];jobID=r.job.id;lastAutoPreview=null;
    showViewerNotice('Resuming: checking saved FBXs and downloading only unfinished animations.');
    renderJob(r.job);
  }catch(e){feedback(e.message);$('resumeBuild').disabled=false;}
};
$('cancel').onclick=async()=>{try{await send('/api/jobs/cancel',{method:'POST'});feedback('Cancellation requested',true);}catch(e){feedback(e.message);}};
const consoleState = $('consoleDrawer');
const callLog=[];
window.MixamoDiagnostics={record(method,route,status){
  // Route and status only. Never include query strings, profile IDs, UUIDs or tokens.
  const safe=String(route).split('?')[0].replace(/\b[a-f0-9]{24,}\b/gi,':id');
  callLog.push(`${new Date().toISOString()} ${method} ${safe} → ${status}`);
  if(callLog.length>250)callLog.splice(0,callLog.length-250);
  updateConsoleText();
}};
let diagnosticsInFlight=false;
async function pollDiagnostics(){
  if(diagnosticsInFlight||consoleState.classList.contains('hidden'))return;
  diagnosticsInFlight=true;
  try{
    const response=await fetch('/api/diagnostics',{headers:{'X-Local-Token':TOKEN}});
    if(response.ok){const data=await response.json();window._mixamoApiEvents=data.events||[];window._mixamoWsEvents=data.websocket||[];updateConsoleText();}
  }catch{}finally{diagnosticsInFlight=false;}
}
function diagnosticReport(){
  const events=Array.isArray(window._mixamoApiEvents)?window._mixamoApiEvents:[];
  const audit=events.map(e=>`${e.at} ${e.method} ${e.route} → ${e.status} (${e.milliseconds} ms)`);
  const ws=(Array.isArray(window._mixamoWsEvents)?window._mixamoWsEvents:[]).map(e=>`${e.at} ${e.event}`);
  return [`Mixamo Studio diagnostics · ${new Date().toISOString()}`,
    `Pipeline: ${activeJob?.id||'none'} (${activeJob?.status||'idle'})`,
    '\n--- MIXAMO PIPELINE ---',logArr.join('\n')||'No pipeline output yet.',
    '\n--- LOCAL API (route, status, duration; no credentials) ---',audit.join('\n')||'No API events',
    '\n--- RANTLIST CLIENT REQUESTS ---',callLog.join('\n')||'No Rantlist requests',
    '\n--- RANTLIST WEBSOCKET HANDSHAKE / SESSION ---',ws.join('\n')||'No WebSocket activity'].join('\n');
}
function updateConsoleText(){if(!consoleState.classList.contains('hidden'))$('consoleText').textContent=diagnosticReport();}
$('toggleConsole').onclick=()=>{consoleState.classList.toggle('hidden');void pollDiagnostics();updateConsoleText();};
$('closeConsole').onclick=()=>consoleState.classList.add('hidden');
async function fullDiagnosticReport(){
  let report=diagnosticReport();
  if(!activeJob?.id)return report;
  try{
    const response=await fetch(`/api/jobs/${encodeURIComponent(activeJob.id)}/log`,{
      headers:{'X-Local-Token':TOKEN}});
    if(response.ok){
      const full=await response.text();
      const start=report.indexOf('\n--- MIXAMO PIPELINE ---');
      const end=report.indexOf('\n--- LOCAL API',start);
      if(start>=0&&end>start)report=report.slice(0,start)+'\n--- MIXAMO PIPELINE (FULL SAVED LOG) ---\n'+full+report.slice(end);
    }
  }catch{}
  return report;
}
$('copyConsole').onclick=async()=>{await pollDiagnostics();try{await navigator.clipboard.writeText(await fullDiagnosticReport());showViewerNotice('Full pipeline log and API diagnostics copied.');}catch(e){showViewerNotice('Clipboard blocked. Use ↓ .txt to save the report.',true);}};
$('downloadConsole').onclick=async()=>{
  await pollDiagnostics();const body=await fullDiagnosticReport();
  const url=URL.createObjectURL(new Blob([body],{type:'text/plain;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=`mixamo-diagnostics-${activeJob?.id||'session'}.txt`;
  document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
};
setInterval(pollDiagnostics,3000);
function renderJob(job){
  if(!job)return;
  activeJob=job;jobID=job.id;
  const running=['starting','running'].includes(job.status);
  $('start').disabled=running;$('cancel').disabled=!running;
  $('resumeBuild').hidden=running||!job.resumable;
  $('resumeBuild').disabled=running;
  $('topJobState').textContent=job.status.toUpperCase();$('globalPhase').textContent=job.phase||job.status;
  const progress=job.resumeProgress;
  $('runStatus').textContent=(job.phase||job.status)+
    (progress?.total?` · ${progress.saved}/${progress.total} FBX saved`:'');
  $('runLED').classList.toggle('running',running);
  $('jobStatus').textContent=job.status;
  $('jobStatus').className='job-label '+(job.status==='completed'?'good':job.status==='failed'?'bad':'');
  $('phase').textContent=job.phase||'';
  $('manualNotice').classList.toggle('hidden',!/manual rigging/i.test(job.phase||''));
  if(/manual rigging/i.test(job.phase||''))showViewerNotice('Complete the Auto-Rigger in Brave; this job will resume automatically.');
  $('outputPath').textContent=`Output: ${job.output}`;
  if(job.oldestLine>cursor)cursor=job.oldestLine;
  if(job.lines?.length){logArr.push(...job.lines);if(logArr.length>1500)logArr=logArr.slice(-1500);$('jobLog').textContent=logArr.join('\n');updateConsoleText();$('jobLog').scrollTop=$('jobLog').scrollHeight;$('consoleText').scrollTop=$('consoleText').scrollHeight;}
  $('activityCount').textContent=logArr.length;
  cursor=job.logCursor;
  $('getGLB').classList.toggle('hidden',job.status!=='completed'||!job.combinedGlb);
  $('getZIP').classList.toggle('hidden',job.status!=='completed'||!job.bundle);
  $('getGLB').href=`/api/jobs/${job.id}/file/glb`;$('getZIP').href=`/api/jobs/${job.id}/file/zip`;
  $('loadFinished').disabled=job.status!=='completed'||!job.combinedGlb;
  if(job.status==='failed'&&job.error)feedback(job.error);
  if(job.status==='completed'&&job.combinedGlb&&lastAutoPreview!==job.id){
    lastAutoPreview=job.id;
    loadLatestPreview();
  }
}
async function loadLatestPreview(){
  if(!activeJob || activeJob.status!=='completed'||!activeJob.combinedGlb)return;
  const url=`/api/jobs/${activeJob.id}/preview`;
  const label=activeJob.output?.split(/[\\/]/).pop()?.replace(/-exports$/,'')||'Finished avatar';
  if(!getViewer()){window.pendingMixamoPreview={url,label,jobId:activeJob.id};return;}
  try{
    sceneTouched=true;
    await getViewer().load(url,label);
    await refreshLibrary();
    const found=libraryModels.find(m=>m.jobId===activeJob.id);
    if(found){librarySelection=found.id;rememberLibrarySelection();setMode('source','library');renderLibrary();await captureForLibrary(found.id);}
    $('saveCurrent').disabled=true;
  }catch(e){showViewerNotice(`Preview failed: ${e.message}`,true);}
}
$('loadFinished').onclick=loadLatestPreview;
$('localGlb').onchange=async e=>{
  const file=e.target.files?.[0];if(!file)return;
  if(!/\.glb$/i.test(file.name))return feedback('Select a .glb file.');
  const url=URL.createObjectURL(file);
  try{
    if(!getViewer()){window.pendingMixamoPreview={url,label:file.name,objectURL:true,file};showViewerNotice('Waiting for Three.js viewer modules to load…');return;}
    sceneTouched=true;
    await getViewer().load(url,file.name,{objectURL:true});
    openedLocalFile=file;librarySelection=null;$('saveCurrent').disabled=false;renderLibrary();
  }catch(err){URL.revokeObjectURL(url);showViewerNotice(`Cannot load GLB: ${err.message}`,true);}
  e.target.value='';
};
for(const [id,fn]of [['prevClip','prev'],['playPause','playPause'],['stopClip','stop'],['nextClip','next'],['resetView','frame']])$(id).onclick=()=>getViewer()?.[fn]?.();
window.addEventListener('mixamo-viewer-ready',()=>{
  if(!window.pendingMixamoPreview)restoreSavedSelection();
  if(window.pendingMixamoPreview){
    const a=window.pendingMixamoPreview;window.pendingMixamoPreview=null;
    sceneTouched=true;
    getViewer()?.load(a.url,a.label,{objectURL:a.objectURL}).then(async()=>{
      if(a.file){openedLocalFile=a.file;librarySelection=null;$('saveCurrent').disabled=false;renderLibrary();}
      else if(a.jobId){
        await refreshLibrary();const found=libraryModels.find(m=>m.jobId===a.jobId);
        if(found){librarySelection=found.id;rememberLibrarySelection();setMode('source','library');renderLibrary();await captureForLibrary(found.id);}
      }
    }).catch(e=>showViewerNotice(e.message,true));
  }
});
// The library is persisted by Flask under MIXAMO_FLASK_WORKSPACE/library/.
let restoringScene=false,sceneTouched=false;
function rememberLibrarySelection(){
  try{if(librarySelection)localStorage.setItem('mixamo-library-last-model',librarySelection);
    else localStorage.removeItem('mixamo-library-last-model');}catch{}
}
function restoreSavedSelection(){
  if(sceneTouched||restoringScene||!getViewer()||!libraryModels.length)return;
  let preferred=null;try{preferred=localStorage.getItem('mixamo-library-last-model');}catch{}
  const selected=libraryModels.find(m=>m.id===preferred) || libraryModels[0];
  if(!selected)return;
  restoringScene=true;
  getViewer().load(selected.glbUrl,selected.name).then(()=>{
    if(sceneTouched)return;
    librarySelection=selected.id;rememberLibrarySelection();
    if(!$('characterFile').files?.length)setMode('source','library');
    renderLibrary();updateSourceLibraryName();
  }).catch(e=>console.warn('Could not restore last model',e)).finally(()=>{restoringScene=false;});
}
async function refreshLibrary(){
  try{const r=await send('/api/library');libraryModels=r.models||[];renderLibrary();restoreSavedSelection();}
  catch(err){console.warn('Library unavailable',err);}
}
function setLibraryExpanded(value){
  libraryExpanded=!!value;
  $('libraryDock').classList.toggle('collapsed',!libraryExpanded);
  $('viewport').classList.toggle('library-expanded',libraryExpanded);
  $('libraryToggle').setAttribute('aria-expanded',String(libraryExpanded));
  $('libraryChevron').textContent=libraryExpanded?'▾':'▴';
  try{localStorage.setItem('mixamo-library-expanded',JSON.stringify(libraryExpanded));}catch{}
}
$('libraryToggle').onclick=()=>setLibraryExpanded(!libraryExpanded);
// Only changes the local scene viewport. No server-side configuration or model data.
const libraryHandle=$('libraryResizeHandle');
const savedHeight=Number(localStorage.getItem('mixamo-library-height'));
function applyLibraryHeight(height,persist=false){
  const host=$('viewport');
  const max=Math.max(166,host.clientHeight-175);
  const value=Math.round(Math.min(max,Math.max(166,height)));
  host.style.setProperty('--library-height',value+'px');
  libraryHandle.setAttribute('aria-valuenow',String(value));
  if(persist)try{localStorage.setItem('mixamo-library-height',String(value));}catch{}
}
applyLibraryHeight(Number.isFinite(savedHeight)&&savedHeight>=166?savedHeight:204);
window.addEventListener('resize',()=>applyLibraryHeight(parseFloat(getComputedStyle($('viewport')).getPropertyValue('--library-height'))||204));
libraryHandle.addEventListener('pointerdown',e=>{
  if(e.button!==0||!libraryExpanded)return;
  e.preventDefault();libraryHandle.setPointerCapture(e.pointerId);
  const starting=parseFloat(getComputedStyle($('viewport')).getPropertyValue('--library-height'))||204;
  const origin=e.clientY;
  function moving(event){if(event.pointerId===e.pointerId)applyLibraryHeight(starting+origin-event.clientY);}
  function finishing(event){if(event.pointerId!==e.pointerId)return;libraryHandle.removeEventListener('pointermove',moving);libraryHandle.removeEventListener('pointerup',finishing);libraryHandle.removeEventListener('pointercancel',finishing);applyLibraryHeight(parseFloat(getComputedStyle($('viewport')).getPropertyValue('--library-height'))||204,true);}
  libraryHandle.addEventListener('pointermove',moving);libraryHandle.addEventListener('pointerup',finishing);libraryHandle.addEventListener('pointercancel',finishing);
});
libraryHandle.addEventListener('keydown',e=>{
  if(!['ArrowUp','ArrowDown','Home'].includes(e.key))return;
  e.preventDefault();setLibraryExpanded(true);
  const now=parseFloat(getComputedStyle($('viewport')).getPropertyValue('--library-height'))||204;
  applyLibraryHeight(e.key==='Home'?204:now+(e.key==='ArrowUp'?48:-48),true);
});
try{setLibraryExpanded(JSON.parse(localStorage.getItem('mixamo-library-expanded')||'true'));}
catch{setLibraryExpanded(true);}
// Texture optimizer: a standalone local GLB variant, not another Blender run.
let textureOptimizationSource=null, textureOptimizationBusy=false;
const textureOptimizeDialog=$('textureOptimizeDialog');
const texturePercent=()=>Number(document.querySelector('input[name="textureOptimizePercent"]:checked')?.value||75);
function textureOptimizedLabel(model, percent){
  return model.name.replace(/-o(?:75|50|25)$/i,'')+'-o'+percent;
}
function showTextureOptimizer(model){
  textureOptimizationSource=model;
  textureOptimizeDialog.querySelector('input[value="75"]').checked=true;
  $('textureOptimizeSource').textContent='Original: '+model.name;
  $('textureOptimizeStatus').className='texture-opt-status';
  $('textureOptimizeStatus').textContent='No changes will be made to the original GLB.';
  updateTextureName();
  textureOptimizeDialog.showModal();
}
function updateTextureName(){
  if(textureOptimizationSource)$('textureOptimizeName').textContent='New Local Library model: '+textureOptimizedLabel(textureOptimizationSource,texturePercent());
}
textureOptimizeDialog.querySelectorAll('input[name="textureOptimizePercent"]').forEach(r=>r.addEventListener('change',updateTextureName));
$('textureOptimizeClose').onclick=$('textureOptimizeCancel').onclick=()=>{if(!textureOptimizationBusy)textureOptimizeDialog.close();};
textureOptimizeDialog.addEventListener('cancel',event=>{if(textureOptimizationBusy)event.preventDefault();});
$('textureOptimizeSubmit').onclick=async()=>{
  if(textureOptimizationBusy||!textureOptimizationSource)return;
  textureOptimizationBusy=true;
  const button=$('textureOptimizeSubmit');button.disabled=true;
  const status=$('textureOptimizeStatus');status.className='texture-opt-status busy';
  status.textContent='Resizing textures and saving the new GLB…';
  try{
    const result=await send('/api/library/'+textureOptimizationSource.id+'/optimize',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({percent:texturePercent()})});
    const r=result.report;
    const reduction=Math.round((1-r.afterBytes/r.beforeBytes)*100);
    const mb=n=>(n/1048576).toFixed(2)+' MiB';
    status.className='texture-opt-status succeeded';
    status.textContent=`Created ${result.model.name}. ${r.optimizedCount} texture(s) resized. GLB: ${mb(r.beforeBytes)} → ${mb(r.afterBytes)} (${reduction>=0?reduction+'% smaller':Math.abs(reduction)+'% larger'}).`;
    await refreshLibrary();
    const found=libraryModels.find(m=>m.id===result.model.id);
    if(found)await loadLibraryModel(found);
    showViewerNotice('Created '+result.model.name+' in Local Model Library');
    button.textContent='Create another variant';
  }catch(e){status.className='texture-opt-status failed';status.textContent='Optimization failed: '+e.message;}
  finally{textureOptimizationBusy=false;button.disabled=false;}
};
function renderLibrary(){updateSourceLibraryName();
  const host=$('libraryCards');host.replaceChildren();
  $('libraryCount').textContent=String(libraryModels.length);
  if(!libraryModels.length){const empty=document.createElement('p');empty.className='library-empty';empty.textContent='Build an avatar or open a GLB and choose Save to Library.';host.append(empty);return;}
  for(const model of libraryModels){
    const card=document.createElement('article');card.className='model-card';
    if(librarySelection===model.id)card.classList.add('selected');
    const open=document.createElement('button');open.className='model-card-main';open.type='button';
    open.title='Load '+model.name+' on the Three.js stage';
    const shot=document.createElement('div');shot.className='model-thumb';
    if(model.thumbnailUrl){const img=document.createElement('img');img.src=model.thumbnailUrl+'?v='+Date.now();img.alt='Stage preview of '+model.name;img.loading='lazy';shot.append(img);}
    else shot.textContent='◇';
    const info=document.createElement('div');info.className='model-card-label';
    const title=document.createElement('strong');title.textContent=model.name;
    info.append(title);open.append(shot,info);
    open.onclick=()=>loadLibraryModel(model);
    const tools=document.createElement('div');tools.className='model-card-actions';
    const download=document.createElement('a');download.href=model.downloadUrl;download.title='Download combined GLB';download.textContent='↓';download.setAttribute('aria-label','Download '+model.name);
    const remove=document.createElement('button');remove.type='button';remove.title='Remove model from library';remove.textContent='×';remove.setAttribute('aria-label','Delete '+model.name+' from library');
    remove.onclick=async()=>{
      if(!confirm(`Remove “${model.name}” from the library?\nOriginal generated exports will stay on disk.`))return;
      try{await send('/api/library/'+model.id,{method:'DELETE'});if(librarySelection===model.id){librarySelection=null;rememberLibrarySelection();}await refreshLibrary();}
      catch(e){showViewerNotice(e.message,true);}
    };
    const publish=document.createElement('button');publish.type='button';publish.title='Publish this GLB to your private Rantlist Stage gallery';publish.textContent='↑ R';publish.setAttribute('aria-label','Publish '+model.name+' to Rantlist');
    publish.onclick=()=>window.RantlistStudio?.publish(model.id,model.name);
    const optimize=document.createElement('button');optimize.type='button';optimize.title='Create texture-optimized GLB (75%, 50% or 25%)';optimize.textContent='◈';optimize.setAttribute('aria-label','Optimize textures of '+model.name);optimize.onclick=()=>showTextureOptimizer(model);
    tools.append(optimize,publish,download,remove);card.append(open,tools);host.append(card);
  }
}
async function captureForLibrary(id){
  const viewer=getViewer();if(!viewer?.captureStage)return;
  try{
    const blob=await viewer.captureStage();if(!blob || blob.size<20)return;
    await send(`/api/library/${id}/thumbnail`,{method:'POST',headers:{'Content-Type':'image/webp'},body:blob});
    const n=viewer.getClips().length;
    await send(`/api/library/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({clips:n})});
    await refreshLibrary();
  }catch(e){console.warn('Stage snapshot unavailable',e);}
}
async function loadLibraryModel(item){
  try{
    if(!getViewer())throw new Error('Three.js viewer has not loaded');
    sceneTouched=true;
    await getViewer().load(item.glbUrl,item.name);
    librarySelection=item.id;rememberLibrarySelection();openedLocalFile=null;$('saveCurrent').disabled=true;
    setMode('source','library');renderLibrary();
    if(!item.thumbnailUrl)await captureForLibrary(item.id);
  }catch(e){showViewerNotice('Cannot open library model: '+e.message,true);}
}
$('captureCurrent').onclick=async()=>{if(librarySelection)await captureForLibrary(librarySelection);};
$('saveCurrent').onclick=async()=>{
  if(!openedLocalFile)return feedback('Open a GLB before saving it to the model library.');
  const body=new FormData();body.set('file',openedLocalFile,openedLocalFile.name);
  $('saveCurrent').disabled=true;
  try{
    const response=await send('/api/library/import',{method:'POST',body});
    librarySelection=response.model.id;rememberLibrarySelection();openedLocalFile=null;
    setMode('source','library');await refreshLibrary();await captureForLibrary(librarySelection);
    showViewerNotice('Saved to Model Library');
  }catch(e){$('saveCurrent').disabled=false;feedback(e.message);}
};
refreshLibrary();
$('captureCurrent').disabled=false;
async function refresh(){
  if(updatePending)return;updatePending=true;
  try{
    const response=await send(`/api/status?since=${cursor}`);
    const s=response.session;
    $('braveStatus').textContent=s.portOpen?'Brave · Connected':'Brave · Offline';$('braveStatus').classList.toggle('online',s.portOpen);
    if(response.presets && !presetImportBusy && Date.now()-lastPresetImportAt>5000)refreshPresets(response.presets);
    if(response.job){if(response.job.id!==jobID){cursor=0;logArr=[];}renderJob(response.job);}
  }catch(e){console.warn('Status update failed',e);}finally{updatePending=false;}
}
refresh();setInterval(refresh,2000);
})();
