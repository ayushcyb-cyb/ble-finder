"use strict";
// Find-BLE frontend. Talks to server.py over /api/*. All distances come from
// the server (which applies per-device calibration); the client only maps them
// onto the radar and handles interaction.

let CFG = {range: 12, tx: -59, n: 2.5};
let RANGE = 12;
const cv = document.getElementById('radar'), ctx = cv.getContext('2d');
const stage = document.getElementById('stage'), tip = document.getElementById('tip');
const findEl = document.getElementById('find');
let DPR = 1, C = {x: 0, y: 0}, R = 0;
let rows = [], view = new Map(), rowEls = new Map();
let selected = null, hover = null, sweep = 0, groupOn = true;

const col = {ACTIVE: '#3ad35a', PASSIVE: '#e3b341', STALE: '#59655c'};
function hueFor(s){let h=0;for(let i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))>>>0;return h%360;}
function colFor(r){return 'hsl('+hueFor(r.address||('#'+r.index))+',70%,58%)';}

// ---- range control ----------------------------------------------------------
const sel = document.getElementById('range');
function buildRange(){
  [2,5,10,15,25,50].concat(CFG.range).filter((v,i,a)=>a.indexOf(v)===i).sort((a,b)=>a-b)
    .forEach(v=>{let o=document.createElement('option');o.value=v;o.textContent=v+' m';
      if(v===CFG.range)o.selected=true;sel.appendChild(o);});
}
sel.onchange = ()=>{RANGE=+sel.value;showRange();};
function showRange(){document.getElementById('rng').textContent='range '+RANGE.toFixed(RANGE<10?1:0)+' m';}
document.getElementById('group').onchange = e=>{groupOn=e.target.checked;poll();};

// ---- canvas sizing ----------------------------------------------------------
function resize(){
  let size=Math.max(300,Math.min(stage.clientWidth,stage.clientHeight));
  DPR=window.devicePixelRatio||1;
  cv.style.width=size+'px';cv.style.height=size+'px';
  cv.width=Math.round(size*DPR);cv.height=Math.round(size*DPR);
  ctx.setTransform(DPR,0,0,DPR,0,0);
  C={x:size/2,y:size/2};R=size/2-30;
}
window.addEventListener('resize',resize);

// ---- positions (with collision declutter) -----------------------------------
function targets(){
  let keep=new Set(), nodes=[];
  for(const r of rows){
    if(r.dist>RANGE)continue;
    keep.add(r.index);
    let rr=(r.dist/RANGE)*R, a=r.angle*Math.PI/180;
    let v=view.get(r.index);
    let tx=C.x+rr*Math.cos(a), ty=C.y+rr*Math.sin(a);
    if(!v){v={x:tx,y:ty,tx,ty,col:colFor(r)};view.set(r.index,v);}
    v.col=colFor(r);v.r=r;v._tx=tx;v._ty=ty;
    nodes.push(v);
  }
  // push overlapping dots apart so each stays clickable (keeps ~distance ring)
  const MIN=15;
  for(let it=0;it<5;it++)for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
    let a=nodes[i],b=nodes[j],dx=b._tx-a._tx,dy=b._ty-a._ty,dd=Math.hypot(dx,dy)||.01;
    if(dd<MIN){let p=(MIN-dd)/2,ux=dx/dd,uy=dy/dd;
      a._tx-=ux*p;a._ty-=uy*p;b._tx+=ux*p;b._ty+=uy*p;}
  }
  for(const v of nodes){
    let dx=v._tx-C.x,dy=v._ty-C.y,m=Math.hypot(dx,dy);
    if(m>R){v._tx=C.x+dx/m*R;v._ty=C.y+dy/m*R;}   // keep inside the dial
    v.tx=v._tx;v.ty=v._ty;
  }
  for(const k of[...view.keys()])if(!keep.has(k))view.delete(k);
}

// ---- draw -------------------------------------------------------------------
function grid(){
  let w=cv.width/DPR,h=cv.height/DPR;ctx.clearRect(0,0,w,h);
  let bg=ctx.createRadialGradient(C.x,C.y,0,C.x,C.y,R);
  bg.addColorStop(0,'#0c1710');bg.addColorStop(1,'#060a07');
  ctx.fillStyle=bg;ctx.beginPath();ctx.arc(C.x,C.y,R,0,7);ctx.fill();
  ctx.lineWidth=1;
  for(let i=1;i<=4;i++){let rr=R*i/4;
    ctx.strokeStyle=i===4?'#255033':'#163022';
    ctx.beginPath();ctx.arc(C.x,C.y,rr,0,7);ctx.stroke();
    ctx.fillStyle='#3c7a50';ctx.font='10px ui-monospace,monospace';
    ctx.fillText((RANGE*i/4).toFixed(RANGE<10?1:0)+' m',C.x+5,C.y-rr+13);}
  ctx.strokeStyle='#122419';
  for(let a=0;a<360;a+=30){let r=a*Math.PI/180;
    ctx.beginPath();ctx.moveTo(C.x,C.y);ctx.lineTo(C.x+R*Math.cos(r),C.y+R*Math.sin(r));ctx.stroke();}
  ctx.fillStyle='#2f6342';ctx.beginPath();ctx.arc(C.x,C.y,3,0,7);ctx.fill();
}
function sweepLine(){
  ctx.save();ctx.translate(C.x,C.y);ctx.rotate(sweep);
  let g=ctx.createLinearGradient(0,0,R,0);
  g.addColorStop(0,'rgba(58,211,90,.20)');g.addColorStop(1,'rgba(58,211,90,0)');
  ctx.strokeStyle=g;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(0,0);ctx.lineTo(R,0);ctx.stroke();ctx.restore();
  sweep=(sweep+0.016)%(2*Math.PI);
}
function dots(){
  for(const[,v]of view){
    let mx=v.tx-v.x,my=v.ty-v.y;
    if(Math.abs(mx)<0.4&&Math.abs(my)<0.4){v.x=v.tx;v.y=v.ty;}else{v.x+=mx*0.12;v.y+=my*0.12;}
    let r=v.r,st=r.state,on=r.index===selected,hv=r.index===hover,sz=on?8:(hv?7:5.5);
    ctx.save();
    if(st==='STALE')ctx.globalAlpha=0.38;
    ctx.shadowColor='rgba(0,0,0,.8)';ctx.shadowBlur=4;
    ctx.beginPath();ctx.arc(v.x,v.y,sz,0,7);
    if(st==='PASSIVE'){ctx.lineWidth=2.5;ctx.strokeStyle=v.col;ctx.stroke();}
    else{ctx.fillStyle=v.col;ctx.fill();}
    ctx.restore();
    if(on||hv){
      ctx.beginPath();ctx.arc(v.x,v.y,sz+4,0,7);ctx.strokeStyle='#eafff0';ctx.lineWidth=1.5;ctx.stroke();
      ctx.fillStyle='#eafff0';ctx.font='bold 11px ui-monospace,monospace';
      ctx.fillText('#'+r.index+(r.name?' '+r.name:''),v.x+10,v.y+4);
    }
  }
}
function frame(){grid();sweepLine();dots();requestAnimationFrame(frame);}

// ---- interaction ------------------------------------------------------------
function hit(mx,my){let best=null,bd=13;
  for(const[,v]of view){let dd=Math.hypot(mx-v.x,my-v.y);if(dd<bd){bd=dd;best=v.r;}}return best;}
cv.addEventListener('mousemove',e=>{
  let rect=cv.getBoundingClientRect(),mx=e.clientX-rect.left,my=e.clientY-rect.top;
  let r=hit(mx,my);hover=r?r.index:null;cv.style.cursor=r?'pointer':'crosshair';
  if(r){tip.style.display='block';tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY+12)+'px';
    tip.innerHTML='<b>'+(r.name||'(no name)')+'</b> &middot; '+(r.vendor||'?')+' &middot; '+r.dist.toFixed(1)+' m';}
  else tip.style.display='none';
});
cv.addEventListener('mouseleave',()=>{hover=null;tip.style.display='none';});
cv.addEventListener('click',e=>{let rect=cv.getBoundingClientRect();
  let r=hit(e.clientX-rect.left,e.clientY-rect.top);if(r)open(r.index);});
cv.addEventListener('wheel',e=>{e.preventDefault();
  RANGE=Math.max(1,Math.min(120,RANGE*(e.deltaY>0?1.12:1/1.12)));showRange();},{passive:false});

// ---- device table (stable, in place) ----------------------------------------
function swatch(r){return '<span class="swatch" style="background:'+
  (r.state==='PASSIVE'?'transparent;border:2px solid '+colFor(r):colFor(r))+
  ';opacity:'+(r.state==='STALE'?.4:1)+'"></span>';}
function drawRows(){
  let inr=rows.filter(r=>r.dist<=RANGE).sort((a,b)=>a.index-b.index);
  document.getElementById('stat').textContent=inr.length+' shown / '+(rows._total||inr.length)+' seen';
  let tbody=document.getElementById('rows'),present=new Set();
  for(const r of inr){
    present.add(r.index);
    let tr=rowEls.get(r.index);
    if(!tr){const idx=r.index;
      tr=document.createElement('tr');tr.addEventListener('click',()=>open(idx));
      for(let i=0;i<8;i++)tr.appendChild(document.createElement('td'));
      rowEls.set(idx,tr);
      let bt=null,bi=Infinity;for(const[i2,t2]of rowEls){if(i2>idx&&i2<bi){bi=i2;bt=t2;}}
      tbody.insertBefore(tr,bt);
    }
    let c=tr.children, badge=r.group_count>1?'<span class="badge">×'+r.group_count+'</span>':'';
    c[0].innerHTML=swatch(r);c[1].textContent=r.index;c[2].textContent=r.dist.toFixed(1);
    c[3].textContent=r.rssi;c[4].textContent=r.state;c[5].textContent=r.vendor||'-';
    c[6].innerHTML=(r.name||'-')+badge;c[7].textContent=r.decoded||'-';
    tr.className=r.index===selected?'sel':'';
  }
  for(const[idx,tr]of rowEls){if(!present.has(idx)){tr.remove();rowEls.delete(idx);}}
}

// ---- find panel -------------------------------------------------------------
async function open(idx){selected=idx;await refreshFind();drawRows();}
function closeFind(){selected=null;findEl.classList.add('hidden');drawRows();}

async function refreshFind(){
  if(selected==null)return;
  let d;try{d=await(await fetch('/api/device/'+selected)).json();}catch(e){return;}
  if(d.error){closeFind();return;}
  let strength=Math.max(0,Math.min(100,(d.rssi+100)/70*100));
  let barCol=strength>66?'#3ad35a':strength>33?'#e3b341':'#e3675a';
  let tr=d.trend, tcls=tr>0.6?'warm':tr<-0.6?'cold':'steady',
      ttxt=tr>0.6?'WARMER &#9650;':tr<-0.6?'COLDER &#9660;':'steady';
  findEl.classList.remove('hidden');
  findEl.innerHTML=
    '<div class="top"><div><div class="nm">'+(d.name||'(no name)')+'</div>'+
      '<div class="sub">'+(d.vendor||'unknown vendor')+' &middot; #'+d.index+' &middot; '+d.state+'</div></div>'+
      '<span class="x" onclick="closeFind()">&times;</span></div>'+
    '<div class="meter"><div style="width:'+strength.toFixed(0)+'%;background:'+barCol+'"></div></div>'+
    '<div class="bigdist"><b>'+d.dist.toFixed(1)+'</b> m'+
      (d.calibrated?' <span class="badge">calibrated</span>':'')+
      ' &middot; <span class="trend '+tcls+'">'+ttxt+'</span></div>'+
    '<canvas id="spark"></canvas>'+
    '<div class="btns">'+
      '<button class="pairbtn" onclick="pair('+d.index+')">Pair</button>'+
      '<button onclick="identify('+d.index+')">Identify (connect)</button>'+
      '<button onclick="calibrate('+d.index+')">Calibrate 1m</button>'+
      '<button onclick="closeFind()">Close</button></div>'+
    '<dl>'+
      '<dt>Address</dt><dd>'+d.address+'</dd>'+
      '<dt>RSSI</dt><dd>'+d.rssi+' dBm'+(d.tx_power!=null?' &middot; tx '+d.tx_power:'')+'</dd>'+
      '<dt>Decoded</dt><dd>'+(d.decoded||'-')+'</dd>'+
      '<dt>Services</dt><dd>'+((d.services_all&&d.services_all.join(', '))||'-')+'</dd>'+
      (d.mfg_hex?'<dt>Mfg data</dt><dd>'+d.mfg_hex+'</dd>':'')+
      (d.model_info?'<dt>Identify</dt><dd>'+d.model_info+'</dd>':'')+
      (d.pair_status?'<dt>Pair</dt><dd>'+d.pair_status+'</dd>':'')+
    '</dl>';
  drawSpark(d.history||[]);
}
function drawSpark(series){
  let c=document.getElementById('spark');if(!c)return;
  let dpr=window.devicePixelRatio||1,w=c.clientWidth||300,h=46;
  c.width=w*dpr;c.height=h*dpr;let g=c.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,w,h);if(series.length<2)return;
  let lo=-100,hi=-30;
  let xs=series.map((p,i)=>i/(series.length-1)*w);
  let ys=series.map(p=>h-((Math.max(lo,Math.min(hi,p.rssi))-lo)/(hi-lo))*h);
  g.strokeStyle='#3ad35a';g.lineWidth=1.5;g.beginPath();
  xs.forEach((x,i)=>{i?g.lineTo(x,ys[i]):g.moveTo(x,ys[i]);});g.stroke();
  g.fillStyle='#9fe6b4';g.beginPath();g.arc(xs[xs.length-1],ys[ys.length-1],2.5,0,7);g.fill();
}
async function identify(idx){
  try{await fetch('/api/identify/'+idx,{method:'POST'});}catch(e){}
  setTimeout(refreshFind,1500);setTimeout(refreshFind,4000);setTimeout(refreshFind,9000);
}
async function pair(idx){
  try{await fetch('/api/pair/'+idx,{method:'POST'});}catch(e){}
  setTimeout(refreshFind,1500);setTimeout(refreshFind,5000);setTimeout(refreshFind,12000);
}
async function calibrate(idx){
  try{await fetch('/api/calibrate/'+idx,{method:'POST'});}catch(e){}
  refreshFind();
}
window.closeFind=closeFind;window.identify=identify;window.calibrate=calibrate;window.pair=pair;

// ---- poll loop --------------------------------------------------------------
async function poll(){
  try{
    let j=await(await fetch('/api/devices?group='+(groupOn?1:0))).json();
    rows=j.devices;rows._total=j.total;
    targets();drawRows();
    if(selected!=null)refreshFind();
  }catch(e){}
}
async function init(){
  try{CFG=await(await fetch('config.json')).json();}catch(e){}
  RANGE=CFG.range;buildRange();showRange();resize();frame();
  poll();setInterval(poll,1000);
}
init();
