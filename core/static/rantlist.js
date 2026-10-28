/* Rantlist Stage gallery in local Mixamo Studio, via localhost-only Flask gateway.
   No portable profile or remote capability is placed in localStorage. */
(() => {
'use strict';
const $ = id => document.getElementById(id);
const localToken = JSON.parse($('bootstrap').textContent).token;
const ui = {connected:false,nickname:null,tab:'local',models:[],selected:null,usedItems:null,maxItems:60};
// Keep only rendered/visible previews in flight to protect the shared Rantlist backend.
const thumbs=new Map(), failedThumbs=new Set(), previewQueue=[];
const previewInFlight=new Set();
let previewActive=0;
const previewObserver=('IntersectionObserver' in window)?new IntersectionObserver(entries=>{
  for(const entry of entries){if(!entry.isIntersecting)continue;
    previewObserver.unobserve(entry.target);
    enqueueThumb(entry.target.dataset.thumbId,entry.target);
  }
},{root:$('rantlistCards'),rootMargin:'130px',threshold:0.01}):null;
function thumbFallback(img,message){
  const holder=img.parentNode;if(!holder)return;
  img.remove();const text=document.createElement('span');text.className='thumb-empty';text.textContent=message;holder.append(text);
}
function runPreviewQueue(){
  while(previewActive<3&&previewQueue.length){
    const next=previewQueue.shift();
    if(!next.img.isConnected)continue;
    const {id,img}=next;
    const cached=thumbs.get(id);
    if(cached){img.src=cached.url;continue;}
    if(failedThumbs.has(id)){thumbFallback(img,'Preview unavailable');continue;}
    if(previewInFlight.has(id)){previewQueue.push(next);break;}
    previewActive++;previewInFlight.add(id);
    (async()=>{
      try{
        const blob=await blobFor(id,'thumbnail');
        if(blob.size<32||!['image/webp','image/png','image/jpeg','image/gif'].includes(blob.type))throw new Error('Not an image');
        // Never accept HTML error pages or broken responses as image thumbnails.
        const url=URL.createObjectURL(blob);thumbs.set(id,{url});
        if(img.isConnected)img.src=url;
      }catch(error){failedThumbs.add(id);if(img.isConnected)thumbFallback(img,'Preview unavailable');}
      finally{previewActive--;previewInFlight.delete(id);runPreviewQueue();}
    })();
  }
}
function enqueueThumb(id,img){
  const cached=thumbs.get(id);
  if(cached){img.src=cached.url;return;}
  previewQueue.push({id,img});runPreviewQueue();
}
function markThumbnail(item,img){
  img.alt='';img.dataset.thumbId=item.id;img.decoding='async';
  img.onerror=()=>{
    if(thumbs.has(item.id)){URL.revokeObjectURL(thumbs.get(item.id).url);thumbs.delete(item.id);}
    failedThumbs.add(item.id);thumbFallback(img,'Preview unavailable');
  };
  if(previewObserver)previewObserver.observe(img);
  else enqueueThumb(item.id,img);
}
async function api(path,options={}) {
  const response=await fetch('/api/rantlist/'+path,{...options,headers:{'X-Local-Token':localToken,...(options.headers||{})}});
  window.MixamoDiagnostics?.record(options.method||'GET', '/api/rantlist/'+path.replace(/[a-f0-9]{24,32}/gi,':id'), response.status);
  if(!response.ok){let reason=`HTTP ${response.status}`;try{reason=(await response.json()).error||reason;}catch{};throw new Error(reason);}
  return response;
}
function announce(message, bad=false){window.MixamoStudioNotice?.show(message,bad);}
function setTab(tab){
  ui.tab=tab;
  $('galleryLocal').classList.toggle('selected',tab==='local');$('galleryRantlist').classList.toggle('selected',tab==='rantlist');
  $('libraryCards').classList.toggle('hidden',tab!=='local');$('rantlistCards').classList.toggle('hidden',tab!=='rantlist');
  $('libraryHint').classList.toggle('hidden',tab!=='local');$('captureCurrent').classList.toggle('hidden',tab!=='local');
  if(tab==='rantlist' && ui.connected)void refresh().catch(e=>announce('Rantlist: '+e.message,true));
}
function updateConnection(){
  $('rantlistDisconnect').classList.toggle('hidden',!ui.connected);
  $('rantlistRefresh').classList.toggle('hidden',!ui.connected);
  $('rantlistImportLabel').classList.toggle('hidden',ui.connected);
  $('rantlistAccountBar').classList.toggle('hidden',!ui.connected);
  const capacity=ui.usedItems==null?'':` · ${ui.usedItems}/${ui.maxItems} Stage assets (${ui.models.length} GLBs visible)`;
  $('rantlistAccountBar').textContent=ui.connected?`Rantlist Stage · ${ui.nickname}${capacity} · Max 20 MiB per GLB`:'';
  $('rantlistCount').textContent=ui.connected?`(${ui.models.length})`:'';
}
async function connectFile(file){
  if(!file||file.size>2*1024*1024)throw new Error('Choose a profile JSON smaller than 2 MiB.');
  let profile;
  try{profile=JSON.parse(await file.text());}catch{throw new Error('This is not valid profile JSON.');}
  if(profile?.format!=='rantlist-profile'||profile?.version!==1||!profile?.identity?.id||!profile?.profile?.nickname)
    throw new Error('Choose a Rantlist version-1 exported profile.');
  if(!confirm(`Connect to Rantlist as “${String(profile.profile.nickname).slice(0,24)}”?\n\nRantlist currently permits only one active session per nickname. This may sign out your existing Rantlist browser tab and may replace newer Rantlist profile details with the fields in this backup. Use a recently exported profile.\n\nYour profile JSON acts as an account credential. Mixamo will keep it only in memory, not save it to disk.\n\nContinue?`))return;
  const response=await api('connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(profile)});
  profile=null; // Release private profile content immediately.
  const session=await response.json();
  ui.connected=!!session.connected;ui.nickname=session.nickname;updateConnection();
  setTab('rantlist');await refresh();announce('Connected to your Rantlist Stage gallery.');
}
$('rantlistProfileFile').addEventListener('change',async event=>{
  try{await connectFile(event.target.files?.[0]);}catch(error){announce('Rantlist: '+error.message,true);}
  finally{event.target.value='';}
});
$('galleryLocal').addEventListener('click',()=>setTab('local'));
$('galleryRantlist').addEventListener('click',()=>setTab('rantlist'));
$('rantlistRefresh').addEventListener('click',()=>{failedThumbs.clear();refresh().catch(e=>announce(e.message,true));});
$('rantlistDisconnect').addEventListener('click',async()=>{
  try{await api('disconnect',{method:'POST'});}catch{}
  ui.connected=false;ui.nickname=null;ui.models=[];ui.selected=null;ui.usedItems=null;clearThumbs();updateConnection();render();
  announce('Disconnected from Rantlist. Your remote library has not been modified.');
});
function clearThumbs(){for(const item of thumbs.values())URL.revokeObjectURL(item.url);thumbs.clear();failedThumbs.clear();previewQueue.length=0;previewObserver?.disconnect();}
async function refresh(){
  if(!ui.connected){render();return;}
  try{
    const data=await(await api('assets')).json();
    ui.models=Array.isArray(data.items)?data.items:[];
    ui.usedItems=Number.isInteger(data.usedItems)?data.usedItems:null;
    ui.maxItems=Number.isInteger(data.maxItems)&&data.maxItems>0?data.maxItems:60;
    updateConnection();render();
  }catch(error){
    if(/expired|reconnect|session/i.test(error.message)) {ui.connected=false;ui.models=[];updateConnection();}
    render();throw error;
  }
}
async function blobFor(id,kind){return (await api(`assets/${encodeURIComponent(id)}/${kind}`)).blob();}
async function loadRemote(item){
  try{
    if(!window.MixamoViewer)throw new Error('Three.js viewer is not ready.');
    announce('Loading Rantlist model…');
    const url=URL.createObjectURL(await blobFor(item.id,'glb'));
    await window.MixamoViewer.load(url,item.name,{objectURL:true});
    window.MixamoStudioSceneSource?.remote();
    ui.selected=item.id;render();
    announce(`${item.name} loaded from your Rantlist gallery.`);
  }catch(error){announce('Rantlist model: '+error.message,true);}
}
async function download(item){
  try{
    const url=URL.createObjectURL(await blobFor(item.id,'download'));
    const a=document.createElement('a');a.href=url;a.download=(item.name||'rantlist-avatar').replace(/[^a-z0-9._-]+/gi,'-')+'.glb';document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),10000);
  }catch(error){announce(error.message,true);}
}
async function erase(item){
  if(!confirm(`Delete “${item.name}” from your REAL Rantlist Stage gallery?\nThis removes the remote asset for your account and may break Stage references. Your local GLB is unaffected.`))return;
  try{await api('assets/'+item.id,{method:'DELETE'});const old=thumbs.get(item.id);if(old)URL.revokeObjectURL(old.url);thumbs.delete(item.id);failedThumbs.delete(item.id);await refresh();announce('Removed from Rantlist Stage.');}
  catch(error){announce('Cannot delete Rantlist model: '+error.message,true);}
}
function render(){
  const host=$('rantlistCards');previewObserver?.disconnect();previewQueue.length=0;host.replaceChildren();
  if(!ui.connected||!ui.models.length){const empty=document.createElement('p');empty.className='library-empty';empty.textContent=ui.connected?'No GLB avatars or models in your Rantlist Stage gallery. Use “↑ R” on any local card to upload one.':'Import your Rantlist profile JSON to connect and browse your private Stage gallery.';host.append(empty);return;}
  for(const item of ui.models){
    const card=document.createElement('article');card.className='model-card';if(ui.selected===item.id)card.classList.add('selected');
    const open=document.createElement('button');open.className='model-card-main';open.type='button';open.title='Load on Mixamo stage';
    const shot=document.createElement('div');shot.className='model-thumb';shot.textContent='◇';
    if(item.thumbnail){const image=document.createElement('img');shot.textContent='';shot.append(image);markThumbnail(item,image);}
    const name=document.createElement('div');name.className='model-card-label';
    const heading=document.createElement('strong');heading.textContent=item.name;
    name.append(heading);open.append(shot,name);open.onclick=()=>loadRemote(item);
    const actions=document.createElement('div');actions.className='model-card-actions';
    const dl=document.createElement('button');dl.title='Download GLB from Rantlist';dl.textContent='↓';dl.onclick=()=>download(item);
    const del=document.createElement('button');del.title='Delete from Rantlist Stage';del.textContent='×';del.onclick=()=>erase(item);
    actions.append(dl,del);card.append(open,actions);host.append(card);
  }
}
// Real publish dialog: never use a native text prompt for an enumerated choice.
const dialog=$('rantlistPublishOverlay'),submit=$('rantlistPublishSubmit'),cancel=$('rantlistPublishCancel');
const status=$('rantlistPublishStatus'),nameInput=$('rantlistPublishName');
let selectedLocalId=null,uploading=false,publishFinished=false;
function publishStatus(message,state=''){
  status.textContent=message;status.className='rantlist-publish-status '+state;
}
function setUploading(value){
  uploading=value;submit.disabled=value||(ui.usedItems!=null&&ui.usedItems>=ui.maxItems);nameInput.disabled=value;
  cancel.disabled=value;
  for(const radio of document.querySelectorAll('input[name="rantlistPublishKind"]'))radio.disabled=value;
}
function closePublish(){if(uploading)return;dialog.classList.add('hidden');selectedLocalId=null;}
cancel.addEventListener('click',closePublish);
dialog.addEventListener('click',e=>{if(e.target===dialog)closePublish();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!dialog.classList.contains('hidden'))closePublish();});
function publish(localId,localName){
  if(!ui.connected){setTab('rantlist');announce('Connect your Rantlist profile before publishing a local model.',true);return;}
  if(uploading)return;
  selectedLocalId=localId;publishFinished=false;
  const proposed=String(localName||'Mixamo model').trim().slice(0,80)||'Mixamo model';
  nameInput.value=proposed;
  $('rantlistPublishSource').textContent=`Source: ${proposed} · Existing GLB in your local Model Library`;
  document.querySelector('input[name="rantlistPublishKind"][value="avatar"]').checked=true;
  const full=ui.usedItems!=null&&ui.usedItems>=ui.maxItems;
  publishStatus(full?`Stage library full (${ui.usedItems}/${ui.maxItems}). The limit includes avatars, models, floors and environments. Delete an unneeded asset from Rantlist before uploading.`:
    `Ready to upload. ${ui.usedItems==null?'Capacity will be checked before upload.':`${ui.usedItems}/${ui.maxItems} Stage assets currently saved.`}`,
    full?'failed':'');
  submit.disabled=full;
  submit.textContent='Upload GLB';cancel.textContent='Cancel';
  dialog.classList.remove('hidden');nameInput.focus();nameInput.select();
}
submit.addEventListener('click',async()=>{
  if(uploading||!selectedLocalId)return;
  const name=nameInput.value.trim(),kind=document.querySelector('input[name="rantlistPublishKind"]:checked')?.value;
  if(!name||name.length>80){publishStatus('Enter a name from 1 to 80 characters.','failed');return;}
  if(!['avatar','model'].includes(kind)){publishStatus('Select Avatar or Model.','failed');return;}
  if(publishFinished){closePublish();return;}
  if(ui.usedItems!=null&&ui.usedItems>=ui.maxItems){
    publishStatus(`Rantlist Stage gallery is full (${ui.usedItems}/${ui.maxItems}). Remove an asset first. No upload was started.`,'failed');return;
  }
  const localId=selectedLocalId;
  setUploading(true);let seconds=0;
  publishStatus('Uploading your GLB to Rantlist Stage…\nWaiting for confirmation from the Rantlist server.','busy');
  const ticker=setInterval(()=>{
    seconds++;
    publishStatus(`Uploading and verifying “${name}” (${seconds}s elapsed)…\nPlease keep this dialog open. No percentage is available from the remote API.`,'busy');
  },1000);
  try{
    const result=await(await api('publish/'+encodeURIComponent(localId),{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,name})
    })).json();
    publishFinished=true;
    const thumbnailText=result.thumbnailSaved?'Stage screenshot saved.':
      `GLB saved, but no stage screenshot was saved${result.thumbnailError?': '+result.thumbnailError:'.'}`;
    publishStatus(`Published successfully: “${result.name}” to your private Rantlist ${result.kind} gallery.\n${thumbnailText}`,'succeeded');
    submit.textContent='Done';cancel.textContent='Close';
    failedThumbs.clear();
    try{await refresh();}catch(error){publishStatus(`GLB published as “${result.name}”.\nGallery refresh failed: ${error.message}. Use ↻ to retry.`, 'succeeded');}
    setTab('rantlist');
    announce(`Published “${result.name}” to Rantlist Stage.`);
  }catch(error){
    publishStatus('Upload failed: '+error.message+'\nNo success was reported. Check your Rantlist gallery before retrying to avoid duplicates.','failed');
    if(/60-item|gallery is full|Stage is full|gallery limit/i.test(error.message)){
      ui.usedItems=ui.maxItems;updateConnection();
    }
    announce('Rantlist publish failed: '+error.message,true);
  }finally{clearInterval(ticker);setUploading(false);}
});
window.RantlistStudio={publish};
void api('status').then(r=>r.json()).then(session=>{
  ui.connected=!!session.connected;ui.nickname=session.nickname;updateConnection();
  if(ui.connected)return refresh();
}).catch(()=>{});
render();updateConnection();
})();
