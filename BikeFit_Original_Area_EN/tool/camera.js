'use strict';
const $=id=>document.getElementById(id);
const video=$('video'), canvas=$('scope'), ctx=canvas.getContext('2d');
const capture=document.createElement('canvas'), captureCtx=capture.getContext('2d');
let stream=null, overlay=null, ranking=[], epoch=0, opening=false;
let timer=null, request=null, updated=0, lastSize='', permissionTimer=null;
function status(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);}
function clearResults(){overlay=null;ranking=[];updated=0;$('metrics').textContent='';$('ranking').replaceChildren();const p=document.createElement('div');p.className='pending';p.textContent='Waiting for camera detection results';$('ranking').append(p);}
function invalidate(){epoch++;clearTimeout(timer);timer=null;if(request)request.abort();request=null;clearResults();}
function errorText(e){return ({NotAllowedError:'Camera access was denied. Allow it in your browser address bar and try again.',NotFoundError:'No camera was found. Check the device connection.',NotReadableError:'Cannot open the camera. Another application may be using it.',OverconstrainedError:'The selected camera is unavailable. Check the device.',SecurityError:'Camera access is blocked. Open the local address in your browser.'})[e.name]||e.message||'Could not connect to the camera. Please try again.';}
async function listDevices(){
  if(!navigator.mediaDevices?.enumerateDevices)return;
  const currentStream=stream;
  const selected=stream?.getVideoTracks()[0]?.getSettings().deviceId||$('devices').value;
  const devices=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput');
  if(currentStream!==stream)return;
  $('devices').replaceChildren(new Option('Choose camera (default)',''));
  devices.forEach((d,i)=>$('devices').add(new Option(d.label||'Camera '+(i+1),d.deviceId)));
  if([...$('devices').options].some(o=>o.value===selected))$('devices').value=selected;
}
function stop(quiet=false){
  invalidate();opening=false;clearTimeout(permissionTimer);
  const old=stream;stream=null;if(old)old.getTracks().forEach(t=>t.stop());
  video.srcObject=null;$('stage').hidden=true;$('empty').hidden=false;lastSize='';
  $('toggle').textContent='Turn on camera';$('devices').disabled=false;
  if(!quiet)status('Camera is off.');
}
function sizeCanvas(){
  const scale=Math.min(1,1920/Math.max(video.videoWidth,video.videoHeight));
  canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);
  lastSize=video.videoWidth+'x'+video.videoHeight;
}
async function connect(){
  stop(true);opening=true;const ticket=epoch;const device=$('devices').value;$('devices').disabled=true;
  $('toggle').textContent='Turn off camera';status('Opening camera. Please allow camera access in your browser…');
  permissionTimer=setTimeout(()=>{if(ticket===epoch&&opening){stop(true);status('Connection timed out. Check your browser camera permissions and try again.',true);}},25000);
  let incoming=null;
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw Error('Camera access is unsupported here. Open the local address in Chrome or Edge.');
    incoming=await navigator.mediaDevices.getUserMedia({audio:false,video:{...(device?{deviceId:{exact:device}}:{}),width:{ideal:1920},height:{ideal:1080}}});
    if(ticket!==epoch){incoming.getTracks().forEach(t=>t.stop());return;}
    stream=incoming;video.srcObject=stream;await video.play();
    if(ticket!==epoch)return;
    if(!video.videoWidth||!video.videoHeight)throw Error('The camera has not provided a video frame. Please try again.');
    clearTimeout(permissionTimer);opening=false;$('devices').disabled=false;listDevices().catch(()=>{});$('empty').hidden=true;$('stage').hidden=false;
    sizeCanvas();
    stream.getVideoTracks().forEach(t=>t.addEventListener('ended',()=>{if(stream===incoming){stop(true);status('The camera was disconnected. Please turn it on again.',true);}},{once:true}));
    status('Camera is on. Measuring enclosed gap areas…');analyzeLoop(ticket);
  }catch(e){if(ticket===epoch){stop(true);status(errorText(e),true);}else if(incoming&&stream!==incoming)incoming.getTracks().forEach(t=>t.stop());}
}
function updateRanking(rows){
  $('ranking').replaceChildren();
  if(!rows.length){const p=document.createElement('div');p.className='pending';p.textContent='No enclosed gap areas were found in the current frame.';$('ranking').append(p);return;}
  rows.slice(0,5).forEach(r=>{const row=document.createElement('div');row.className='rank';row.style.setProperty('--rank',r.color);const left=document.createElement('span'),number=document.createElement('b'),area=document.createElement('span');number.textContent=String(r.rank).padStart(2,'0');left.append(number,'Rank '+r.rank+'');area.textContent=r.area_px2.toLocaleString('en-GB')+' px²';row.append(left,area);$('ranking').append(row);});
}
async function analyzeLoop(ticket){
  if(ticket!==epoch||!stream)return;
  const controller=new AbortController();request=controller;
  const timeout=setTimeout(()=>controller.abort(),30000);
  let delay=100;
  try{
    if(video.readyState<2||video.paused||!video.videoWidth)throw Error('Waiting for a camera frame…');
    capture.width=canvas.width;capture.height=canvas.height;captureCtx.drawImage(video,0,0,capture.width,capture.height);
    const payload={frame_base64:capture.toDataURL('image/jpeg',.92).split(',')[1]};
    const response=await fetch('/api/frame',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':window.SESSION_TOKEN},body:JSON.stringify(payload),signal:controller.signal});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Detection failed. Retrying…');
    if(ticket!==epoch)return;
    const image=new Image();image.src='data:image/png;base64,'+result.overlay_base64;await image.decode();
    if(ticket!==epoch)return;
    overlay=image;ranking=result.ranking;updated=performance.now();updateRanking(ranking);
    window.dispatchEvent(new CustomEvent('bikefit:result',{detail:{result,overlay:image}}));
    $('metrics').dataset.time=(result.elapsed_ms/1000).toFixed(1);
    status('Live detection · '+result.candidates+' enclosed regions · Showing top '+ranking.length+'');
  }catch(e){
    if(ticket===epoch){clearResults();status(e.name==='AbortError'?'This frame timed out. Retrying…':e.message,true);delay=1000;}
  }finally{
    clearTimeout(timeout);if(request===controller)request=null;
    if(ticket===epoch&&stream)timer=setTimeout(()=>analyzeLoop(ticket),delay);
  }
}
function render(){
  if(stream&&!opening&&video.videoWidth&&video.videoHeight){
    const size=video.videoWidth+'x'+video.videoHeight;
    if(size!==lastSize){invalidate();sizeCanvas();status('Video size changed. Updating detection…');analyzeLoop(epoch);}
    ctx.clearRect(0,0,canvas.width,canvas.height);
    if(overlay&&updated){
      const age=(performance.now()-updated)/1000;
      if(age<Math.max(5,Number($('metrics').dataset.time)*2+1)){
        ctx.drawImage(overlay,0,0);
        $('metrics').textContent='Frame processing: '+$('metrics').dataset.time+' s · Updated '+age.toFixed(1)+' s ago';
      }else{clearResults();status('The previous result expired. Waiting for the next frame…');}
    }
  }
  requestAnimationFrame(render);
}
$('toggle').onclick=()=>{if(stream||opening)stop();else connect();};
$('devices').onchange=()=>{if(stream)connect();};
navigator.mediaDevices?.addEventListener('devicechange',()=>listDevices().catch(()=>{}));
window.addEventListener('pagehide',()=>stop(true));
listDevices().catch(()=>{});
requestAnimationFrame(render);
