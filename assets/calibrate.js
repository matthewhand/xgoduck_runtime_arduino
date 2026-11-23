const $=id=>document.getElementById(id);
const MOTORS=[10,11,12,13,14,20,21,22,23,24,30,31,32,33,34];
let statusBusy=false, transitioning=false, session=null, centering=null, presentMask=0;
let canStart=false;
let held=Array(15).fill(false);
let imuCalibrationActive=false;

async function post(path, body={}){
  const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body),signal:AbortSignal.timeout(1600)});
  const x=await r.json().catch(()=>({}));
  if(!r.ok) throw Object.assign(new Error(x.detail||'request failed'),{status:r.status});
  return x;
}
function showError(e){$('message').textContent=e.message||String(e);}

MOTORS.forEach((id,i)=>{
  $('joints').insertAdjacentHTML('beforeend',`<div class="cal-row" id="row${i}">
    <div class="cal-meta"><b>ID ${id}</b><span id="raw${i}">Waiting for feedback</span></div>
    <div class="cal-actions"><span id="state${i}">—</span><button data-center="${i}" disabled>Set center &amp; hold</button></div>
  </div>`);
});

function refreshRows(){
  document.querySelectorAll('[data-center]').forEach(btn=>{
    const i=+btn.dataset.center;
    btn.disabled=!session||transitioning||centering!==null||imuCalibrationActive||held[i]||!(presentMask&(1<<i));
    $(`row${i}`).classList.toggle('done',Boolean(session&&held[i]));
    $(`state${i}`).textContent=!session?'—':centering===i?'Centering…':held[i]?'Holding center':'Unloaded';
  });
  $('start').textContent=session?'Unload all':'Start calibration';
  $('start').disabled=transitioning||imuCalibrationActive||centering!==null||(!session&&!canStart);
  $('exit').disabled=!session||transitioning;
}

document.querySelectorAll('[data-center]').forEach(btn=>{
  btn.onclick=async()=>{
    if(btn.disabled)return;
    const i=+btn.dataset.center;
    const owner=session;
    centering=i;
    refreshRows();
    $('message').textContent=`Setting the center of ID ${MOTORS[i]}…`;
    try{
      await post('cal/center',{index:i,session:owner});
      if(session===owner)$('message').textContent=`ID ${MOTORS[i]} is holding its center.`;
    }catch(e){if(session===owner)showError(e);}
    finally{centering=null;refreshRows();}
  };
});

async function enter(){
  if($('start').disabled)return;
  const starting=!session;
  session??=Array.from(crypto.getRandomValues(new Uint8Array(16)), byte=>byte.toString(16).padStart(2,'0')).join('');
  const owner=session;
  transitioning=true;
  refreshRows();
  try{
    await post('cal/enter',{session:owner});
    if(session!==owner)return;
    held.fill(false);
    $('message').textContent='All servos are unloaded. Turn one joint by hand, then set its center.';
  }catch(e){
    if(starting&&session===owner){
      // The request can reach the UNO Q even if the browser never receives the reply.
      releaseOnLeave(owner);
      session=null;
    }
    showError(e);
  }finally{
    transitioning=false;
    refreshRows();
    if(document.hidden&&session===owner)exit();
  }
}
async function exit(){
  if(!session||transitioning)return;
  const owner=session;
  session=null;
  transitioning=true;
  canStart=false;
  held.fill(false);
  refreshRows();
  try{
    const state=await post('cal/exit',{session:owner});
    $('message').textContent=state.mode==='shadow'?'Calibration closed. All servos are unloaded.'
      :'This page no longer owns a calibration session.';
  }catch(e){showError(e);}
  finally{transitioning=false;refreshRows();}
}
function releaseOnLeave(owner){
  navigator.sendBeacon('/api/cal/exit',new Blob([JSON.stringify({session:owner})],{type:'application/json'}));
}
$('start').onclick=enter;
$('exit').onclick=exit;
window.addEventListener('pagehide',()=>{
  if(!session)return;
  releaseOnLeave(session);
  session=null;
  canStart=false;
  refreshRows();
});
document.addEventListener('visibilitychange',()=>{if(document.hidden)exit();});

setInterval(async()=>{
  if(statusBusy||document.hidden)return;
  statusBusy=true;
  const owner=session;
  try{
    if(owner&&!transitioning){
      try{await post('cal/heartbeat',{session:owner});}
      catch(e){if(e.status===409&&session===owner&&!transitioning)session=null;}
    }
    const r=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(1600)});
    if(!r.ok)throw new Error('status read failed');
    const s=await r.json();
    if(owner&&session===owner&&!transitioning&&s.mode!=='calibrate')session=null;
    canStart=['off','shadow'].includes(s.mode)&&s.enabled===false;
    presentMask=s.raw_mask||0;
    held=s.cal_done||Array(15).fill(false);
    imuCalibrationActive=!!s.imu_calibration?.active;
    $('mode').textContent=s.mode==='calibrate'
      ? (session?'Calibration active':'Calibration active on another page') : 'Calibration closed';
    if(s.last_error)$('message').textContent=s.last_error;
    if(s.raw_pos)s.raw_pos.forEach((v,i)=>{
      $(`raw${i}`).textContent=presentMask&(1<<i)?'Encoder '+v:'No servo feedback';
    });
    refreshRows();
  }catch(e){showError(e);}
  finally{statusBusy=false;}
},250);
