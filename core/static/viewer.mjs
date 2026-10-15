/* Three.js preview: model, materials, rig + all GLB clips; lil-gui scene editor. */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import GUI from 'lil-gui';

const $ = id => document.getElementById(id);
const host = $('sceneCanvas');
const scene = new THREE.Scene();
const player = {clip:-1,speed:1,loop:'Repeat',crossfade:0.4,
  play:()=>play(),pause:()=>pause(),stop:()=>stop(),previous:()=>previous(),next:()=>next()};
const appearance = {background:'#202b3c',floor:'#354052',floorVisible:true,grid:false,
  keyIntensity:2.3,fillIntensity:1.2,ambientIntensity:1.25,rimIntensity:1.6,
  shadows:true,exposure:1.05,autoRotate:false,frame:()=>frameModel()};
scene.background=new THREE.Color(appearance.background);
const renderer = new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});
renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
renderer.outputColorSpace=THREE.SRGBColorSpace;
renderer.toneMapping=THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure=appearance.exposure;
renderer.shadowMap.enabled=true;
renderer.shadowMap.type=THREE.PCFSoftShadowMap;
host.appendChild(renderer.domElement);
const camera=new THREE.PerspectiveCamera(42,1,0.04,400);
camera.position.set(0,1.7,4.5);
const controls=new OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;controls.dampingFactor=.08;controls.target.set(0,1.1,0);
controls.minDistance=.2;controls.maxDistance=120;
const amb=new THREE.HemisphereLight(0xdde9ff,0x3e4655,appearance.ambientIntensity);scene.add(amb);
const keyLight=new THREE.DirectionalLight(0xffe6cb,appearance.keyIntensity);keyLight.position.set(4,9,6);keyLight.castShadow=true;
keyLight.shadow.mapSize.set(2048,2048);keyLight.shadow.camera.near=.1;keyLight.shadow.camera.far=80;
keyLight.shadow.bias=-.00025;keyLight.shadow.normalBias=.015;keyLight.shadow.camera.left=-8;
keyLight.shadow.camera.right=8;keyLight.shadow.camera.top=8;keyLight.shadow.camera.bottom=-8;
scene.add(keyLight);
const fillLight=new THREE.DirectionalLight(0xa7caff,appearance.fillIntensity);fillLight.position.set(-6,4,2);scene.add(fillLight);
const rimLight=new THREE.DirectionalLight(0x9aafff,appearance.rimIntensity);rimLight.position.set(-4,5,-5);scene.add(rimLight);
const floor=new THREE.Mesh(new THREE.PlaneGeometry(220,220),new THREE.MeshStandardMaterial({color:appearance.floor,roughness:.94,metalness:0}));
floor.rotation.x=-Math.PI/2;floor.receiveShadow=true;floor.position.y=-.012;scene.add(floor);
const grid=new THREE.GridHelper(24,24,0x677991,0x46566c);
grid.position.y=.003;grid.material.transparent=true;grid.material.opacity=.27;grid.visible=appearance.grid;scene.add(grid);
const loader=new GLTFLoader();
const draco=new DRACOLoader();
draco.setDecoderPath('https://cdn.jsdelivr.net/npm/three@0.180.0/examples/jsm/libs/draco/');
draco.setWorkerLimit(2);loader.setDRACOLoader(draco);
const clock=new THREE.Clock();
let model=null,mixer=null,clips=[],currentAction=null,loadedUrl='',currentClip=-1;
let paused=false,ended=false,requestSequence=0,loadedBounds=null;

function size(){const w=Math.max(1,host.clientWidth),h=Math.max(1,host.clientHeight);renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
new ResizeObserver(size).observe(host);size();

function disposeModel(){
  if(mixer&&model){mixer.stopAllAction();mixer.uncacheRoot(model);}
  if(model){scene.remove(model);model.traverse(o=>{
    if(o.geometry)o.geometry.dispose?.();
    for(const m of (Array.isArray(o.material)?o.material:[o.material]))if(m){
      for(const key of ['map','normalMap','roughnessMap','metalnessMap','emissiveMap','aoMap','alphaMap'])m[key]?.dispose?.();
      m.dispose?.();
    }
  });}
  model=null;mixer=null;clips=[];currentAction=null;currentClip=-1;loadedBounds=null;
}
function status(message,isError=false){
  $('viewerState').textContent=String(message).toUpperCase().slice(0,60);
  window.MixamoStudioNotice?.show(message,isError);
}
function setPlayingUI(on){$('playPause').textContent=on?'Ⅱ':'▶';$('playPause').title=on?'Pause':'Play';}
function setNowPlaying(text){$('nowPlaying').textContent=text;}
function setLoop(action){
  if(!action)return;
  const once=player.loop==='Once';
  action.setLoop(once?THREE.LoopOnce:THREE.LoopRepeat,once?1:Infinity);
  action.clampWhenFinished=once;
}
function updateClipGUI(){
  clipController.destroy();
  const options={};
  if(clips.length){for(let i=0;i<clips.length;i++){
    let label=clips[i].name||`Animation ${i+1}`;
    if(Object.hasOwn(options,label))label+=` [${i+1}]`;
    options[label]=i;
  }}else options['No clips loaded']=-1;
  player.clip=clips.length?0:-1;
  clipController=animationFolder.add(player,'clip',options).name('Action').onChange(v=>switchClip(Number(v)));
  clipController.updateDisplay();
}
function switchClip(index,fade=player.crossfade){
  if(!mixer||!clips[index])return;
  const previous=currentAction;
  const nextAction=mixer.clipAction(clips[index]);
  setLoop(nextAction);
  if(previous===nextAction){nextAction.reset().play();}
  else{
    nextAction.enabled=true;nextAction.reset().setEffectiveWeight(1).setEffectiveTimeScale(1).play();
    if(previous){if(fade>0)previous.crossFadeTo(nextAction,fade,false);else previous.stop();}
    else if(fade>0)nextAction.fadeIn(fade);
  }
  currentAction=nextAction;currentClip=index;player.clip=index;ended=false;
  clipController?.updateDisplay();paused=false;mixer.timeScale=player.speed;
  setPlayingUI(true);setNowPlaying(clips[index].name||`Animation ${index+1}`);
  $('viewerState').textContent='PLAYING';
}
function play(){
  if(!mixer||!clips.length)return;
  if(!currentAction || ended){switchClip(Math.max(0,currentClip),0);return;}
  if(currentAction.isRunning()===false){currentAction.play();}
  paused=false;mixer.timeScale=player.speed;setPlayingUI(true);$('viewerState').textContent='PLAYING';
}
function pause(){if(!mixer)return;paused=true;mixer.timeScale=0;setPlayingUI(false);$('viewerState').textContent='PAUSED';}
function playPause(){if(!mixer)return;if(paused||!currentAction)play();else pause();}
function stop(){if(!mixer)return;mixer.stopAllAction();currentAction=null;paused=true;ended=false;setPlayingUI(false);$('viewerState').textContent='STOPPED';}
function next(){if(clips.length)switchClip((Math.max(-1,currentClip)+1)%clips.length);}
function previous(){if(clips.length)switchClip((Math.max(0,currentClip)-1+clips.length)%clips.length);}
function frameModel(){
  if(!loadedBounds){camera.position.set(0,1.6,4.2);controls.target.set(0,1,0);controls.update();return;}
  const center=loadedBounds.getCenter(new THREE.Vector3());
  const dimensions=loadedBounds.getSize(new THREE.Vector3());
  const maxDim=Math.max(dimensions.x,dimensions.y,dimensions.z,.1);
  const vFov=THREE.MathUtils.degToRad(camera.fov);
  const hFov=2*Math.atan(Math.tan(vFov/2)*camera.aspect);
  const distance=Math.max(dimensions.y/(2*Math.tan(vFov/2)),dimensions.x/(2*Math.tan(hFov/2)),maxDim*.8)*1.55;
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(distance*.05,dimensions.y*.11,distance));
  camera.near=Math.max(.005,distance/300);camera.far=Math.max(300,distance*90);camera.updateProjectionMatrix();
  controls.maxDistance=Math.max(20,distance*12);controls.update();
}
async function load(url,label,{objectURL=false}={}){
  const req=++requestSequence;
  status('Loading 3D model…');
  try{
    const result=await loader.loadAsync(url,(event)=>{
      if(req!==requestSequence)return;
      if(event.total)$('viewerState').textContent=`LOADING ${Math.round(event.loaded/event.total*100)}%`;
    });
    if(req!==requestSequence){result.scene.traverse(o=>o.geometry?.dispose?.());return;}
    disposeModel();model=result.scene;scene.add(model);
    model.traverse(o=>{if(o.isMesh||o.isSkinnedMesh){o.castShadow=true;o.receiveShadow=true;}});
    clips=result.animations||[];
    loadedBounds=new THREE.Box3().setFromObject(model);
    if(loadedBounds.isEmpty() || !Number.isFinite(loadedBounds.min.y))throw new Error('Model has no measurable geometry');
    floor.position.y=loadedBounds.min.y-.012;
    grid.position.y=loadedBounds.min.y+.003;
    frameModel();mixer=new THREE.AnimationMixer(model);
    mixer.addEventListener('finished',(event)=>{
      if(event.action===currentAction && player.loop==='Once'){
        paused=true;ended=true;setPlayingUI(false);$('viewerState').textContent='FINISHED';
      }
    });
    updateClipGUI();
    $('assetName').textContent=label||'Loaded model';
    $('clipCount').textContent=`${clips.length} CLIPS`;
    $('emptyState').classList.add('hidden');
    loadedUrl=label||url;
    if(clips.length)switchClip(0,0);else{setNowPlaying('No animations in this GLB');setPlayingUI(false);}
    window.MixamoStudioNotice?.dismiss();
    $('viewerState').textContent=clips.length?'PLAYING':'MODEL LOADED';
    return {clips:clips.length,mesh:true};
  }catch(err){if(req===requestSequence)status(`GLB load error: ${err.message}`,true);throw err;}
  finally{if(objectURL)URL.revokeObjectURL(url);}
}
const gui=new GUI({container:$('guiMount'),title:'STAGE CONTROLS',width:265});
const animationFolder=gui.addFolder('Animation mixer');
let clipController=animationFolder.add(player,'clip',{'No clips loaded':-1}).name('Action');
animationFolder.add(player,'speed',.1,3,.05).name('Speed ×').onChange(value=>{if(mixer&&!paused)mixer.timeScale=value;});
animationFolder.add(player,'crossfade',0,2,.05).name('Blend (seconds)');
animationFolder.add(player,'loop',['Repeat','Once']).name('Loop mode').onChange(()=>{if(currentAction)setLoop(currentAction);});
animationFolder.add(player,'play').name('Play / resume');
animationFolder.add(player,'pause').name('Pause');
animationFolder.add(player,'stop').name('Stop');
animationFolder.add(player,'previous').name('Previous clip');
animationFolder.add(player,'next').name('Next clip');
animationFolder.open();
const lighting=gui.addFolder('Lighting');
lighting.add(appearance,'keyIntensity',0,6,.05).name('Key').onChange(v=>keyLight.intensity=v);
lighting.add(appearance,'fillIntensity',0,5,.05).name('Fill').onChange(v=>fillLight.intensity=v);
lighting.add(appearance,'rimIntensity',0,5,.05).name('Rim').onChange(v=>rimLight.intensity=v);
lighting.add(appearance,'ambientIntensity',0,4,.05).name('Ambient').onChange(v=>amb.intensity=v);
lighting.add(appearance,'exposure',.3,2.5,.05).name('Exposure').onChange(v=>renderer.toneMappingExposure=v);
lighting.add(appearance,'shadows').name('Shadows').onChange(v=>{keyLight.castShadow=v;renderer.shadowMap.enabled=v;renderer.shadowMap.needsUpdate=true;});
const world=gui.addFolder('Environment');
world.addColor(appearance,'background').name('Background').onChange(v=>scene.background.set(v));
world.addColor(appearance,'floor').name('Floor color').onChange(v=>floor.material.color.set(v));
world.add(appearance,'floorVisible').name('Floor visible').onChange(v=>floor.visible=v);
world.add(appearance,'grid').name('Grid').onChange(v=>grid.visible=v);
world.add(appearance,'autoRotate').name('Orbit automatically').onChange(v=>controls.autoRotate=v);
world.add(appearance,'frame').name('Frame character');
lighting.close();world.close();
const animate=()=>{
  requestAnimationFrame(animate);
  const delta=Math.min(clock.getDelta(),.08);
  if(mixer && !paused)mixer.update(delta);
  controls.update();renderer.render(scene,camera);
};animate();
function captureStage(){
  if(!model)return null;
  // Capture the *Three.js canvas*, excluding Studio UI overlays.
  renderer.render(scene,camera);
  const source=renderer.domElement;
  const canvas=document.createElement('canvas');canvas.width=360;canvas.height=220;
  const ctx=canvas.getContext('2d');if(!ctx)return null;
  const scale=Math.min(canvas.width/source.width,canvas.height/source.height);
  const drawW=Math.round(source.width*scale),drawH=Math.round(source.height*scale);
  ctx.fillStyle=appearance.background;ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.drawImage(source,Math.round((canvas.width-drawW)/2),Math.round((canvas.height-drawH)/2),drawW,drawH);
  return new Promise(resolve=>canvas.toBlob(resolve,'image/webp',0.78));
}
window.MixamoViewer={load,play,pause,playPause,stop,next,prev:previous,frame:frameModel,
  captureStage,getClips:()=>clips.map(c=>c.name)};
window.dispatchEvent(new CustomEvent('mixamo-viewer-ready'));
