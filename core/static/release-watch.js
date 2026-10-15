/* Persistent release watcher for a tab kept open across Flask restarts. */
(()=>{
  'use strict';
  const KEY='mixamo-studio-seen-release-v1';
  let overlay, lastPrompt='', polling=false;
  function node(name,attrs={},content=''){
    const e=document.createElement(name);
    for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);
    if(content)e.textContent=content;
    return e;
  }
  function hide(version){localStorage.setItem(KEY,version);lastPrompt='';overlay?.remove();overlay=null;}
  function display(release){
    if(lastPrompt===release.version)return;
    lastPrompt=release.version;
    overlay?.remove();
    overlay=node('div',{class:'mixamo-release-backdrop',role:'presentation'});
    const panel=node('section',{class:'mixamo-release-dialog',role:'dialog','aria-modal':'true','aria-label':'Studio updated'});
    const top=node('div',{class:'mixamo-release-eyebrow'},'SOFTWARE UPDATE · '+release.version);
    const title=node('h2',{},'Mixamo Studio updated');
    const desc=node('p',{},'A new release is installed. Refresh to load the updated interface.');
    const list=node('ul');
    for(const c of (release.changes||[]).slice(0,6))list.appendChild(node('li',{},String(c)));
    const actions=node('div',{class:'mixamo-release-actions'});
    const later=node('button',{type:'button',class:'mixamo-release-later'},'Later');
    const reload=node('button',{type:'button',class:'mixamo-release-reload'},'Reload studio');
    later.addEventListener('click',()=>hide(release.version));
    reload.addEventListener('click',()=>{hide(release.version);window.location.reload();});
    actions.append(later,reload);panel.append(top,title,desc,list,actions);overlay.append(panel);document.body.append(overlay);
  }
  async function check(){
    if(polling)return;polling=true;
    try{
      const res=await fetch('/api/release',{cache:'no-store'});
      if(!res.ok)throw Error('release endpoint unavailable');
      const data=await res.json();
      if(!/^\d+\.\d+\.\d+$/.test(data.version||''))return;
      const versionLabel=document.getElementById('studioVersion');
      if(versionLabel)versionLabel.textContent='v'+data.version;
      const seen=localStorage.getItem(KEY);
      if(!seen){localStorage.setItem(KEY,data.version);return;}
      if(seen!==data.version)display(data);
    }catch(_){/* A brief outage is expected while Flask restarts. */}
    finally{polling=false;}
  }
  check();setInterval(check,5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
})();
