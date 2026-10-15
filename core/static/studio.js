/* Mixamo Studio controller: isolated from Three.js so pipeline remains functional offline. */
(() => {
'use strict';
const init = JSON.parse(document.getElementById('bootstrap').textContent);
const TOKEN = init.token;
const $ = id => document.getElementById(id);
let sourceMode = 'path', presetMode = 'saved', cursor = 0, jobID = null;
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
const fields = ['characterPath','presetPathInput','blender','draco','webp','timeout','port'];
const checks = {skip_upload:'skipUpload',skip_download:'skipDownload',confirm_upload:'confirmUpload',require_textures:'requireTextures',no_draco:'noDraco',no_webp:'noWebp',continue_on_error:'continueOnError',dry_run:'dryRun'};
function setMode(type, mode) {
  const isSource = type === 'source'; if(isSource) sourceMode = mode; else presetMode = mode;
  const second = isSource ? 'upload' : 'saved';
  for (const kind of ['path', second]) $(type+kind[0].toUpperCase()+kind.slice(1)).classList.toggle('hidden', kind !== mode);
  $(type+'PathButton').classList.toggle('selected', mode==='path');
  $(type+(isSource?'Upload':'Saved')+'Button').classList.toggle('selected', mode!== 'path');
  storeSettings();
}
$('sourcePathButton').onclick = () => setMode('source','path');
$('sourceUploadButton').onclick = () => setMode('source','upload');
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
  setMode('source',state.sourceMode==='upload'?'upload':'path');
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
$('savePreset').onclick=async()=>{
  const file=$('presetFile').files[0]; if(!file)return feedback('Select a JSON file from Motion Collector.');
  const data=new FormData();data.append('file',file);
  try{const response=await send('/api/presets',{method:'POST',body:data});refreshPresets(response.presets);$('presetSelect').value=response.filename;storeSettings();feedback(`Preset saved: ${response.count} clips`,true);}catch(e){feedback(e.message);}
};
function buildForm(){
  const d=new FormData();d.set('source_mode',sourceMode);d.set('preset_mode',presetMode);
  if(sourceMode==='path')d.set('character_path',$('characterPath').value.trim());
  else if($('characterFile').files[0])d.set('character_file',$('characterFile').files[0]);
  if(presetMode==='saved')d.set('preset',$('presetSelect').value);else d.set('preset_path',$('presetPathInput').value.trim());
  for(const id of ['draco','webp','timeout','port','blender'])d.set(id,$(id).value);
  for(const [f,id]of Object.entries(checks))d.set(f,$(id).checked?'true':'false');
  return d;
}
$('start').onclick=async()=>{
  feedback('');storeSettings();$('start').disabled=true;
  try{const r=await send('/api/jobs',{method:'POST',body:buildForm()});cursor=0;logArr=[];jobID=r.job.id;lastAutoPreview=null;showViewerNotice(`Build started · ${r.animations} animations`);renderJob(r.job);}
  catch(e){feedback(e.message);$('start').disabled=false;}
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
  $('topJobState').textContent=job.status.toUpperCase();$('globalPhase').textContent=job.phase||job.status;
  $('runStatus').textContent=job.phase||job.status;
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
    if(found){librarySelection=found.id;rememberLibrarySelection();renderLibrary();await captureForLibrary(found.id);}
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
        if(found){librarySelection=found.id;rememberLibrarySelection();renderLibrary();await captureForLibrary(found.id);}
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
    librarySelection=selected.id;rememberLibrarySelection();renderLibrary();
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
function renderLibrary(){
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
    tools.append(publish,download,remove);card.append(open,tools);host.append(card);
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
    librarySelection=item.id;rememberLibrarySelection();openedLocalFile=null;$('saveCurrent').disabled=true;renderLibrary();
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
    librarySelection=response.model.id;rememberLibrarySelection();openedLocalFile=null;await refreshLibrary();await captureForLibrary(librarySelection);
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
    if(response.presets)refreshPresets(response.presets);
    if(response.job){if(response.job.id!==jobID){cursor=0;logArr=[];}renderJob(response.job);}
  }catch(e){console.warn('Status update failed',e);}finally{updatePending=false;}
}
refresh();setInterval(refresh,2000);
})();
