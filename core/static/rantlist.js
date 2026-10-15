/* Rantlist Stage gallery in local Mixamo Studio, via localhost-only Flask gateway.
   No portable profile or remote capability is placed in localStorage. */
(() => {
'use strict';
const $ = id => document.getElementById(id);
const localToken = JSON.parse($('bootstrap').textContent).token;
const ui = {connected:false,nickname:null,tab:'local',models:[],selected:null};
const thumbs = new Map();
async function api(path,options={}) {
  const response=await fetch('/api/rantlist/'+path,{...options,headers:{'X-Local-Token':localToken,...(options.headers||{})}});
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
  $('rantlistAccountBar').textContent=ui.connected?`Rantlist Stage · ${ui.nickname} · Private avatar & model galleries · Max 20 MiB per GLB · 60 items across all Stage libraries`:'';
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
$('rantlistRefresh').addEventListener('click',()=>refresh().catch(e=>announce(e.message,true)));
$('rantlistDisconnect').addEventListener('click',async()=>{
  try{await api('disconnect',{method:'POST'});}catch{}
  ui.connected=false;ui.nickname=null;ui.models=[];ui.selected=null;clearThumbs();updateConnection();render();
  announce('Disconnected from Rantlist. Your remote library has not been modified.');
});
function clearThumbs(){for(const url of thumbs.values())URL.revokeObjectURL(url);thumbs.clear();}
async function refresh(){
  if(!ui.connected){render();return;}
  try{
    const data=await(await api('assets')).json();
    ui.models=Array.isArray(data.items)?data.items:[];
    updateConnection();render();
  }catch(error){
    if(/expired|reconnect|session/i.test(error.message)) {ui.connected=false;ui.models=[];updateConnection();}
    render();throw error;
  }
}
async function blobFor(id,kind){return (await api(`assets/${encodeURIComponent(id)}/${kind}`)).blob();}
async function thumbnail(id,img){
  try{
    let url=thumbs.get(id);
    if(!url){url=URL.createObjectURL(await blobFor(id,'thumbnail'));thumbs.set(id,url);}
    if(img.isConnected)img.src=url;
  }catch{if(img.isConnected)img.alt='No remote thumbnail';}
}
async function loadRemote(item){
  try{
    if(!window.MixamoViewer)throw new Error('Three.js viewer is not ready.');
    announce('Loading Rantlist model…');
    const url=URL.createObjectURL(await blobFor(item.id,'glb'));
    await window.MixamoViewer.load(url,item.name,{objectURL:true});
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
  try{await api('assets/'+item.id,{method:'DELETE'});const old=thumbs.get(item.id);if(old)URL.revokeObjectURL(old);thumbs.delete(item.id);await refresh();announce('Removed from Rantlist Stage.');}
  catch(error){announce('Cannot delete Rantlist model: '+error.message,true);}
}
function render(){
  const host=$('rantlistCards');host.replaceChildren();
  if(!ui.connected||!ui.models.length){const empty=document.createElement('p');empty.className='library-empty';empty.textContent=ui.connected?'No GLB avatars or models in your Rantlist Stage gallery. Use “↑ R” on any local card to upload one.':'Import your Rantlist profile JSON to connect and browse your private Stage gallery.';host.append(empty);return;}
  for(const item of ui.models){
    const card=document.createElement('article');card.className='model-card';if(ui.selected===item.id)card.classList.add('selected');
    const open=document.createElement('button');open.className='model-card-main';open.type='button';open.title='Load on Mixamo stage';
    const shot=document.createElement('div');shot.className='model-thumb';shot.textContent='◇';
    if(item.thumbnail){const image=document.createElement('img');image.alt='Rantlist preview for '+item.name;shot.textContent='';shot.append(image);void thumbnail(item.id,image);}
    const name=document.createElement('div');name.className='model-card-label';
    const heading=document.createElement('strong');heading.textContent=item.name;
    const secondary=document.createElement('small');secondary.textContent=`${item.kind==='avatar'?'Stage avatar':'Stage model'} · ${(item.size/1048576).toFixed(1)} MiB`;
    name.append(heading,secondary);open.append(shot,name);open.onclick=()=>loadRemote(item);
    const actions=document.createElement('div');actions.className='model-card-actions';
    const dl=document.createElement('button');dl.title='Download GLB from Rantlist';dl.textContent='↓';dl.onclick=()=>download(item);
    const del=document.createElement('button');del.title='Delete from Rantlist Stage';del.textContent='×';del.onclick=()=>erase(item);
    actions.append(dl,del);card.append(open,actions);host.append(card);
  }
}
async function publish(localId){
  if(!ui.connected){setTab('rantlist');announce('Import a Rantlist profile JSON first, then publish again.',true);return;}
  const choice=prompt('Publish to Rantlist Stage gallery as “avatar” (character) or “model” (scene asset)?','avatar');
  if(choice===null)return;
  const kind=choice.trim().toLowerCase();
  if(kind!=='avatar'&&kind!=='model'){announce('Choose avatar or model.',true);return;}
  if(!confirm(`Upload this GLB to the authenticated Rantlist ${kind} gallery?\nRantlist applies its own file limits and profile storage quota.`))return;
  try{
    announce('Uploading GLB to Rantlist Stage…');
    const result=await(await api('publish/'+encodeURIComponent(localId),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind})})).json();
    await refresh();setTab('rantlist');
    announce(`Published “${result.name}” to your Rantlist ${kind} gallery${result.thumbnailSaved?' with stage preview':' (preview could not be saved)'}.`);
  }catch(error){announce('Rantlist publish failed: '+error.message,true);}
}
window.RantlistStudio={publish};
void api('status').then(r=>r.json()).then(session=>{
  ui.connected=!!session.connected;ui.nickname=session.nickname;updateConnection();
  if(ui.connected)return refresh();
}).catch(()=>{});
render();updateConnection();
})();
