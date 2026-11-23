// Draw measured samples on a moving time axis, with a break at each missing sample.
(() => {
 const byId = id => document.getElementById(id);
 const canvas = byId('plot'), ctx = canvas.getContext('2d');
 const clock = t => new Date(t*1000).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
 let state={}, key, data, timer, request, error=false, held=null;
 const timeOf = s => s ? Date.parse(s)/1000 : NaN;
 const format = n => n.toLocaleString('ko-KR',{maximumFractionDigits:Math.abs(n)<1?3:1});
 function endTime(){
  const now=Date.now()/1000;
  if(state.mode!=='replay')return now;
  const elapsed=Math.max(0,now-timeOf(state.started));
  return Math.min(data.end,data.start+elapsed*8);
 }
 function draw(){
  if(document.hidden || !data)return;
  const width=canvas.clientWidth, height=canvas.clientHeight, ratio=window.devicePixelRatio||1;
  if(width<100 || height<50)return;
  if(canvas.width!==Math.round(width*ratio)||canvas.height!==Math.round(height*ratio)){
   canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);
  }
  ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);
  const end=held??endTime(), start=end-data.span, l=56,r=width-18,top=9,b=height-23;
  const points=data.points.filter(([t])=>t>=start&&t<=end);
  const values=points.map(p=>p[1]).filter(Number.isFinite);
  const max=Math.max(0,...values),min=Math.min(0,...values),hi=max===min?max+1:max;
  const x=t=>l+(r-l)*(t-start)/data.span, y=v=>b-(b-top)*(v-min)/(hi-min);
  ctx.font='12px system-ui';ctx.fillStyle='#536863';ctx.lineWidth=1;
  for(const v of [hi,(hi+min)/2,min]){
   ctx.strokeStyle='#dfe8e5';ctx.beginPath();ctx.moveTo(l,y(v));ctx.lineTo(r,y(v));ctx.stroke();
   ctx.textAlign='right';ctx.fillText(format(v),l-8,y(v)+4);
  }
  for(const t of [start,(start+end)/2,end]){
   ctx.textAlign=t===end?'right':t===start?'left':'center';ctx.fillText(clock(t),x(t),height-4);
  }
  const replay=state.mode==='replay';
  const markers=[[replay?data.onset:timeOf(state.applied),'#b96215','주입'],
   [replay?timeOf(state.window):timeOf(state.detected),'#aa395b',replay?'분석 구간 끝':'이상 감지'],
   [replay?data.removal:timeOf(state.recovered),'#2f6387','복구']];
  ctx.setLineDash([3,4]);
  for(const [t,color] of markers)if(t>=start&&t<=end){ctx.strokeStyle=color;ctx.beginPath();ctx.moveTo(x(t),top);ctx.lineTo(x(t),b);ctx.stroke();}
  ctx.setLineDash([]);
  ctx.lineWidth=2;ctx.strokeStyle='#007466';ctx.fillStyle='#007466';
  let previous=null,last=null;
  for(const [t,v] of points){
   if(!Number.isFinite(v)){previous=null;continue;}
   if(previous && t-previous[0]<=data.step*1.1){
    ctx.beginPath();ctx.moveTo(x(previous[0]),y(previous[1]));ctx.lineTo(x(t),y(v));ctx.stroke();
   }else{ctx.beginPath();ctx.arc(x(t),y(v),2,0,Math.PI*2);ctx.fill();}
   previous=last=[t,v];
  }
  if(last){ctx.beginPath();ctx.arc(x(last[0]),y(last[1]),3,0,Math.PI*2);ctx.fill();}
  const latest=points.at(-1);
  byId('reading').textContent=Number.isFinite(latest?.[1]) && end-latest[0]<=2*data.step?format(latest[1])+' '+data.unit:'—';
  byId('plotStatus').textContent=error?'조회 지연':held!==null?'일시 정지':!values.length?'이 구간에 관측값 없음':replay?(end===data.end?'재생 완료':'기록 재생 · 8배속'):'최근 5분 · 10초 간격';
  byId('events').textContent=markers.filter(([t])=>t<=end && t>=start).map(([t,_,label])=>label+' '+clock(t)).join('   ·   ');
 }
 async function load(){
  const id=key, controller=new AbortController();request=controller;
  try{
   const response=await fetch('/series',{signal:controller.signal,cache:'no-store'});
   if(!response.ok)throw Error();
   const d=await response.json();
   if(id!==key || (d.run||'idle')!==key)return;
   data=d;error=false;byId('plotName').textContent=d.title+' · '+d.subject.replace('->',' → ');
   canvas.setAttribute('aria-label',byId('plotName').textContent);draw();
  }catch{
   if(controller.signal.aborted || id!==key)return;
   error=true;byId('plotStatus').textContent='관측값 조회 지연';draw();
  }finally{if(id===key && !(state.mode==='replay' && data))timer=setTimeout(load,10000);}
 }
 window.syncWallChart = s=>{
  state=s;const id=s.run||'idle';
  if(key!==id){
   key=id;clearTimeout(timer);request?.abort();data=null;held=null;error=false;byId('hold').textContent='일시 정지';
   ctx.clearRect(0,0,canvas.width,canvas.height);byId('reading').textContent='—';
   byId('events').textContent='';byId('plotName').textContent='관측 지표';byId('plotStatus').textContent='조회 중';load();
  }
 };
 byId('hold').onclick=()=>{if(!data)return;held=held===null?endTime():null;byId('hold').textContent=held===null?'일시 정지':'현재 시점으로';draw();};
 setInterval(draw,500);
})();
