/* Experimental SPA panels, parked out of the dashboard (plan, phase 1). NOT loaded by
   spa/index.html. Kept for reference until each has a validated definition and a test:

   - market read (computeView / drawView): the thresholds VIEW_TH are unvalidated, and the
     residual percentile is taken over ALL hours of 30 days, so it measures the daily cycle
     rather than how tight today is — it must be conditioned on hour of day and day type;
   - market-regime scatter and volatility / gas->power beta: built on log returns, which are
     undefined for prices <= 0 (Italian zones clear at -0.01 EUR/MWh); the peak window is
     h in [8,19) in the BROWSER's time zone, and the Italian peak is 08:00-20:00 Europe/Rome.

   They depend on helpers from index.html ($, col, setup, css, niceTicks, valueAtNow, pctl, DAY).
*/

/* ---------- panel 5: volatility (power vs gas) ---------- */
function dailyPeakOff(S){
  const idx=S.index, p=col(S,"price_zonal"), acc={};
  for(let i=0;i<idx.length;i++){ if(p[i]==null) continue;
    const d=new Date(idx[i]), wd=d.getDay(); if(wd<1||wd>5) continue;   // business days: consistent sqrt(252)
    const key=idx[i].slice(0,10), h=d.getHours(), peak=(h>=8&&h<19);
    (acc[key]=acc[key]||{pk:[],off:[],all:[]});
    acc[key].all.push(p[i]); (peak?acc[key].pk:acc[key].off).push(p[i]); }
  const dates=Object.keys(acc).sort(), mean=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:null;
  return {dates, peak:dates.map(d=>mean(acc[d].pk)), off:dates.map(d=>mean(acc[d].off)), base:dates.map(d=>mean(acc[d].all))};
}
function logRet(v){const r=[null]; for(let i=1;i<v.length;i++) r.push((v[i]>0&&v[i-1]>0)?Math.log(v[i]/v[i-1]):null); return r;}
function rollVol(r,win){const out=r.map(()=>null);
  for(let i=win;i<r.length;i++){const w=r.slice(i-win+1,i+1).filter(x=>x!=null);
    if(w.length<win*0.6) continue; const m=w.reduce((a,b)=>a+b,0)/w.length;
    const v=w.reduce((a,b)=>a+(b-m)**2,0)/(w.length-1); out[i]=Math.sqrt(v*252)*100;} return out;}
function betaOf(x,y){const xs=[],ys=[]; for(let i=0;i<x.length;i++) if(x[i]!=null&&y[i]!=null){xs.push(x[i]);ys.push(y[i]);}
  if(xs.length<5) return null; const mx=xs.reduce((a,b)=>a+b,0)/xs.length, my=ys.reduce((a,b)=>a+b,0)/ys.length;
  let cov=0,vx=0; for(let i=0;i<xs.length;i++){cov+=(xs[i]-mx)*(ys[i]-my);vx+=(xs[i]-mx)**2;} return vx>0?cov/vx:null;}
function lastOf(a){for(let i=a.length-1;i>=0;i--) if(a[i]!=null) return a[i]; return null;}
/* ---------- panel: market regime (phase scatter) ---------- */
function median(a){ const s=a.filter(x=>x!=null).slice().sort((x,y)=>x-y); if(!s.length) return null; const m=s.length>>1; return s.length%2?s[m]:(s[m-1]+s[m])/2; }
function pctlOf(a,v){ const s=a.filter(x=>x!=null); return s.length? s.filter(x=>x<=v).length/s.length : 0; }
function drawRegime(D){
  const box=$("#rgReadout"), cap=$("#rgCaption"); if(!box) return;
  const P=dailyPeakOff(D.series), base=P.base, dates=P.dates, vol=rollVol(logRet(base),21);
  const pts=[]; for(let i=0;i<dates.length;i++) if(vol[i]!=null && base[i]!=null) pts.push({v:vol[i], p:base[i]});
  const R=pts.slice(-40);
  if(R.length<5){ box.innerHTML=`<div class="wx-msg">not enough data for a regime read</div>`; cap.textContent=""; return; }
  const vmed=median(R.map(x=>x.v)), pmed=median(R.map(x=>x.p));
  // Descriptive labels: the quadrant says where you are, the caption says what it means.
  // Evocative names (calm/firm/choppy/stressed) needed a lookup table to read.
  const STATE={
    "low price · low vol":  {c:"--obs",      say:"abundant supply, with little risk priced in"},
    "high price · low vol": {c:"--price",    say:"expensive but orderly, gas setting the price without stress"},
    "low price · high vol": {c:"--residual", say:"renewable-driven swings on thin margins, with negative-price risk"},
    "high price · high vol":{c:"--warn",     say:"scarcity conditions, with spike risk"} };
  const label=(v,p)=> (p>=pmed?"high price":"low price") + " \u00b7 " + (v>=vmed?"high vol":"low vol");
  const cur=R.at(-1), state=label(cur.v,cur.p);
  const persist=R.slice(-7).filter(x=>label(x.v,x.p)===state).length;
  const vpct=Math.round(pctlOf(R.map(x=>x.v),cur.v)*100), ppct=Math.round(pctlOf(R.map(x=>x.p),cur.p)*100);
  box.innerHTML=
    `<div class="fstat"><div class="fl">Market state</div><div class="fv" style="color:var(${STATE[state].c});font-size:14px;line-height:1.35">${state.replace(" \u00b7 ","<br>")}</div></div>`+
    `<div class="fstat"><div class="fl">Volatility now</div><div class="fv">${cur.v.toFixed(0)}<small> % \u00b7 ${vpct}th pct</small></div></div>`+
    `<div class="fstat"><div class="fl">Price now</div><div class="fv">${cur.p.toFixed(0)}<small> \u20ac \u00b7 ${ppct}th pct</small></div></div>`+
    `<div class="fstat"><div class="fl">Persistence</div><div class="fv">${persist}<small>/7 days here</small></div></div>`;
  const cv=$("#rgCanvas"); const {ctx,w,h}=setup(cv); const pad={l:48,r:16,t:14,b:28};
  const vs=R.map(x=>x.v), ps=R.map(x=>x.p);
  const pf=(a,b,f)=>[a-(b-a)*f,b+(b-a)*f];
  const [vlo,vhi]=pf(Math.min(...vs),Math.max(...vs),.10), [plo,phi]=pf(Math.min(...ps),Math.max(...ps),.10);
  const x=v=>pad.l+(v-vlo)/((vhi-vlo)||1)*(w-pad.l-pad.r), y=p=>h-pad.b-(p-plo)/((phi-plo)||1)*(h-pad.t-pad.b);
  ctx.font="10px "+css("--mono"); ctx.textBaseline="middle";
  niceTicks(plo,phi,4).forEach(v=>{const yy=y(v);ctx.strokeStyle=css("--line");ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.fillStyle=css("--ink-dim");ctx.textAlign="right";ctx.fillText(v.toFixed(0),pad.l-6,yy);});
  ctx.textAlign="center";ctx.fillStyle=css("--ink-dim");
  niceTicks(vlo,vhi,4).forEach(v=>ctx.fillText(v.toFixed(0)+"%",x(v),h-pad.b+13));
  // median split
  ctx.strokeStyle=css("--line-2");ctx.setLineDash([4,4]);ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(x(vmed),pad.t);ctx.lineTo(x(vmed),h-pad.b);ctx.stroke();
  ctx.beginPath();ctx.moveTo(pad.l,y(pmed));ctx.lineTo(w-pad.r,y(pmed));ctx.stroke();ctx.setLineDash([]);
  // quadrant labels
  ctx.font="9px "+css("--mono");ctx.fillStyle=css("--ink-faint");
  const corner=(tx,ty,l1,l2,align)=>{ctx.textAlign=align;ctx.fillText(l1,tx,ty);ctx.fillText(l2,tx,ty+10);};
  corner(pad.l+5, h-pad.b-19, "LOW VOL",  "LOW PRICE",  "left");
  corner(pad.l+5, pad.t+5,    "LOW VOL",  "HIGH PRICE", "left");
  corner(w-pad.r-5, h-pad.b-19,"HIGH VOL","LOW PRICE",  "right");
  corner(w-pad.r-5, pad.t+5,  "HIGH VOL", "HIGH PRICE", "right");
  // trajectory (last 8)
  ctx.strokeStyle=css("--line-2");ctx.lineWidth=1;ctx.beginPath();
  R.slice(-8).forEach((pt,i)=>{const px=x(pt.v),py=y(pt.p);i?ctx.lineTo(px,py):ctx.moveTo(px,py);});ctx.stroke();
  // points, recency -> alpha + size
  R.forEach((pt,i)=>{const rec=i/(R.length-1); ctx.fillStyle=css(STATE[label(pt.v,pt.p)].c); ctx.globalAlpha=.22+.78*rec;
    ctx.beginPath();ctx.arc(x(pt.v),y(pt.p),3+3*rec,0,7);ctx.fill();});
  ctx.globalAlpha=1;
  ctx.strokeStyle=css("--ink");ctx.lineWidth=1.5;ctx.beginPath();ctx.arc(x(cur.v),y(cur.p),6.5,0,7);ctx.stroke();
  ctx.fillStyle=css("--ink-dim");ctx.textAlign="center";ctx.fillText("realised volatility",(pad.l+w-pad.r)/2,h-3);
  cap.innerHTML=`The market is in a <b style="color:var(${STATE[state].c})">${state}</b> regime \u2014 ${STATE[state].say}. `+
    `<b class="mono" style="color:var(--ink)">${persist}/7</b> of the last days sit here. Vol ${vpct}th percentile, price ${ppct}th.`+
    (D.live?``:` <span style="color:var(--ink-faint)">(sample)</span>`);
}

/* ---------- panel: market regime (phase scatter) ---------- END */
function drawVol(D){
  const win=21, P=dailyPeakOff(D.series);
  const peakVol=rollVol(logRet(P.peak),win), offVol=rollVol(logRet(P.off),win), baseRet=logRet(P.base);
  const F=(D.fuels&&D.fuels.index)?D.fuels:SAMPLE_FUELS, gasByDate={};
  F.index.forEach((d,i)=>{const g=F.columns.gas_ttf.values[i]; if(g!=null) gasByDate[d]=g;});
  const gasAligned=P.dates.map(d=>gasByDate[d]!=null?gasByDate[d]:null);
  const gasVol=rollVol(logRet(gasAligned),win), beta=betaOf(logRet(gasAligned),baseRet);
  const pv=lastOf(peakVol), ov=lastOf(offVol), gv=lastOf(gasVol);
  const ratio=(pv!=null&&ov!=null&&ov>0)?pv/ov:null;
  $("#volReadout").innerHTML=
    `<div class="fstat"><div class="fl">Power vol \u2014 peak</div><div class="fv">${pv!=null?pv.toFixed(0):'\u2013'}<small> %</small></div><div class="fsub">${win}d realized, annualized</div></div>`+
    `<div class="fstat"><div class="fl">Power vol \u2014 off-peak</div><div class="fv">${ov!=null?ov.toFixed(0):'\u2013'}<small> %</small></div></div>`+
    `<div class="fstat"><div class="fl">Gas vol (TTF)</div><div class="fv">${gv!=null?gv.toFixed(0):'\u2013'}<small> %</small></div></div>`+
    `<div class="fstat"><div class="fl">Peak / off \u00b7 gas\u2192power \u03b2</div><div class="fv">${ratio!=null?ratio.toFixed(1)+'\u00d7':'\u2013'}</div><div class="fsub">\u03b2 ${beta!=null?beta.toFixed(2):'\u2013'} \u00b7 1% gas \u2192 \u03b2% power</div></div>`;
  const cv=$("#volCanvas"); const {ctx,w,h}=setup(cv); const pad={l:44,r:16,t:14,b:24};
  const T=P.dates.map(d=>new Date(d).getTime());
  const series=[[peakVol,css("--price")],[offVol,css("--residual")],[gasVol,css("--warn")]];
  const allv=series.flatMap(s=>s[0]).filter(x=>x!=null);
  if(allv.length<2){$("#volCaption").textContent="not enough data for a volatility estimate";return;}
  const vmax=Math.max(...allv), vmin=0;
  const x=v=>pad.l+(v-T[0])/(T.at(-1)-T[0])*(w-pad.l-pad.r), y=v=>h-pad.b-(v-vmin)/(vmax-vmin)*(h-pad.t-pad.b);
  ctx.font="10px "+css("--mono"); ctx.textBaseline="middle";
  niceTicks(vmin,vmax,4).forEach(v=>{const yy=y(v);ctx.strokeStyle=css("--line");ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();
    ctx.fillStyle=css("--ink-dim");ctx.textAlign="right";ctx.fillText(v.toFixed(0)+"%",pad.l-6,yy);});
  ctx.fillStyle=css("--ink-dim");ctx.textAlign="center";
  niceTicks(T[0],T.at(-1),6).forEach(v=>{const d=new Date(v);ctx.fillText(("0"+d.getDate()).slice(-2)+"/"+("0"+(d.getMonth()+1)).slice(-2),x(v),h-pad.b+13);});
  for(const [vals,color] of series){ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();let started=false;
    for(let i=0;i<vals.length;i++){ if(vals[i]==null){started=false;continue;} const px=x(T[i]),py=y(vals[i]); started?ctx.lineTo(px,py):ctx.moveTo(px,py); started=true;} ctx.stroke();}
  const live=!!(D.fuels&&D.fuels.index)&&D.live;
  const ratioTxt = ratio==null ? `` :
    (ratio>=1 ? `Peak power swings <b class="mono" style="color:var(--ink)">${ratio.toFixed(1)}\u00d7</b> off-peak. `
              : `Off-peak swings <b class="mono" style="color:var(--ink)">${(1/ratio).toFixed(1)}\u00d7</b> peak. `);
  $("#volCaption").innerHTML=ratioTxt+
    (beta!=null?`Gas\u2192power \u03b2 = <b class="mono" style="color:var(--ink)">${beta.toFixed(2)}</b>: a 1% TTF move maps to ~${(beta*100).toFixed(0)}% of a baseload-power move. `:``)+
    `Power carries its own risk on top \u2014 renewable and demand shocks the merit order can't absorb.`+
    (live?``:` <span style="color:var(--ink-faint)">(sample)</span>`);
}

// draw only the active tab's canvases (hidden canvases have width 0 -> must draw on show)
/* ---------- panel: today's read (fundamental view synthesis) ---------- */
const VIEW_TH={resHi:60, resLo:40, nl:500, storTight:-3, storComf:3, dSrmc:5, volHi:1.25};
function computeView(D){
  const S=D.series, sigs=[];
  // ----- demand axis -----
  const res=col(S,"residual_load"), resNow=valueAtNow(res,S.index).v;
  const cut=Date.now()-30*DAY, rr=[];
  for(let i=0;i<S.index.length;i++){const t=new Date(S.index[i]).getTime(); if(t>=cut&&res[i]!=null) rr.push(res[i]);}
  const resPct = rr.length? Math.round(pctl(rr,resNow)*100) : null;
  if(resPct!=null) sigs.push({axis:"demand", dir: resPct>=VIEW_TH.resHi?1:resPct<=VIEW_TH.resLo?-1:0,
    str:Math.abs(resPct-50)/10, text:`residual at the ${resPct}th percentile of the month`});
  const nl = (D.forecast&&D.forecast.delta_mean!=null)?D.forecast.delta_mean:null;
  if(nl!=null) sigs.push({axis:"demand", dir: nl>VIEW_TH.nl?1:nl<-VIEW_TH.nl?-1:0,
    str:Math.abs(nl)/500, text:`tomorrow's net load ${nl>=0?'+':''}${(nl/1000).toFixed(1)} GW vs today`});
  // ----- cost axis -----
  const stor = (D.storage&&D.storage.latest&&D.storage.latest.vs_hist_avg!=null)?D.storage.latest.vs_hist_avg:null;
  if(stor!=null) sigs.push({axis:"cost", dir: stor<=VIEW_TH.storTight?1:stor>=VIEW_TH.storComf?-1:0,
    str:Math.abs(stor)/3, text:`gas storage ${stor>=0?'+':''}${stor} pp vs the seasonal norm`});
  const F=(D.fuels&&D.fuels.index)?D.fuels:(typeof SAMPLE_FUELS!=="undefined"?SAMPLE_FUELS:null);
  let dSrmc=null;
  if(F&&F.columns&&F.columns.srmc){ const sv=F.columns.srmc.values.filter(x=>x!=null); if(sv.length>=6) dSrmc=sv.at(-1)-sv.at(-6); }
  if(dSrmc!=null) sigs.push({axis:"cost", dir: dSrmc>=VIEW_TH.dSrmc?1:dSrmc<=-VIEW_TH.dSrmc?-1:0,
    str:Math.abs(dSrmc)/VIEW_TH.dSrmc, text:`the CCGT cost floor (SRMC) ${dSrmc>=0?'+':''}${dSrmc.toFixed(0)} €/MWh over the week`});
  // ----- conviction: volatility -----
  const P=dailyPeakOff(S), pvs=rollVol(logRet(P.peak),21), pv=lastOf(pvs);
  const vv=pvs.filter(x=>x!=null).sort((a,b)=>a-b), volMed=vv.length?vv[vv.length>>1]:null;
  const volHigh=(pv!=null&&volMed!=null)?pv>volMed*VIEW_TH.volHi:false;
  // ----- combine -----
  const axisDir=ax=>sigs.filter(s=>s.axis===ax).reduce((a,s)=>a+s.dir,0);
  const demandDir=axisDir("demand"), costDir=axisDir("cost");
  const sgn=x=>x>0?1:x<0?-1:0, dD=sgn(demandDir), cD=sgn(costDir);
  let bias;
  if(dD>0&&cD>0) bias={word:"constructive", cls:"up", dir:1};
  else if(dD<0&&cD<0) bias={word:"soft", cls:"dn", dir:-1};
  else if(dD*cD<0) bias={word:"two-sided", cls:"mix", dir:0};
  else if(dD>0||cD>0) bias={word:"mildly constructive", cls:"up", dir:1};
  else if(dD<0||cD<0) bias={word:"mildly soft", cls:"dn", dir:-1};
  else bias={word:"balanced", cls:"flat", dir:0};
  // rationale: two strongest non-zero signals
  const top=sigs.filter(s=>s.dir!==0).sort((a,b)=>b.str-a.str).slice(0,2).map(s=>s.text);
  // falsifier: from the dominant axis
  const dom = Math.abs(costDir)>=Math.abs(demandDir)?"cost":"demand";
  const domDir = dom==="cost"?cD:dD;
  let fals;
  if(dom==="cost") fals = domDir>0 ? "gas or CO₂ sells off, or storage catches up to the norm"
                                   : "gas or CO₂ rallies, or storage tightens";
  else            fals = domDir>0 ? "tomorrow's wind or solar beats the forecast, softening net load"
                                   : "tomorrow's renewables underdeliver, tightening net load";
  if(bias.dir===0) fals = "either the demand or the cost side breaks the current stand-off — watch gas and tomorrow's renewables";
  return {sigs, demandDir:dD, costDir:cD, volHigh, bias, rationale:top, falsifier:fals,
          live: !!(D.forecast&&D.forecast.days) };
}
function drawView(D){
  const v=computeView(D);
  const col_={up:"var(--warn)",dn:"var(--residual)",mix:"var(--est)",flat:"var(--ink-dim)"}[v.bias.cls];
  $("#viewPanel").style.borderLeftColor=col_;
  $("#viewBias").innerHTML=`Fundamentals lean <b style="color:${col_}">${v.bias.word}</b> on price`;
  const arrow=d=>d>0?'<span class="ar" style="color:var(--warn)">▲</span>':d<0?'<span class="ar" style="color:var(--residual)">▼</span>':'<span class="ar" style="color:var(--ink-dim)">→</span>';
  $("#viewBoard").innerHTML=
    `<span class="vchip">Demand ${arrow(v.demandDir)}</span>`+
    `<span class="vchip">Costs ${arrow(v.costDir)}</span>`+
    `<span class="vchip">Vol <b style="color:${v.volHigh?'var(--warn)':'var(--ink-dim)'}">${v.volHigh?'elevated':'normal'}</b></span>`;
  $("#viewRationale").innerHTML = v.rationale.length
    ? `Reading: ${v.rationale.join("; ")}.` : `No signal stands out — fundamentals are balanced.`;
  $("#viewFalsifier").innerHTML = `<b>Weakens if:</b> ${v.falsifier}.`;
  $("#viewCaveat").textContent = "A fundamental read, not a spot-vs-forward view — the forward curve is commercial data we don't carry."
    + (v.live? "" : "  (sample data)");
}



/* ---- markup removed from index.html (Overview "Today's read", Risk tab) ----
  <!-- Panel: today's read (fundamental view synthesis) -->
  <section class="panel view" id="viewPanel">
    <div class="view-head">
      <div class="view-eyebrow">Today's read</div>
      <h2 id="viewBias">—</h2>
      <div class="view-board" id="viewBoard"></div>
    </div>
    <div class="view-body">
      <p class="view-rationale" id="viewRationale"></p>
      <p class="view-falsifier" id="viewFalsifier"></p>
      <p class="view-caveat" id="viewCaveat"></p>
    </div>
  </section>

  <div class="tab-panel" id="tab-risk" hidden>
  <!-- Panel 5 — volatility: power vs gas -->
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>Volatility — power vs gas</h2>
        <div class="thesis">Annualized realized volatility (21-day). Peak power swings far more
          than off-peak, and power vol is partly gas vol passed through the merit order — the β
          measures how much of a gas move actually reaches power.</div>
      </div>
      <div class="legend">
        <span><span class="swatch" style="background:var(--price)"></span>power peak</span>
        <span><span class="swatch" style="background:var(--residual)"></span>power off-peak</span>
        <span><span class="swatch" style="background:var(--warn)"></span>gas</span>
      </div>
    </div>
    <div class="fuel-readout" id="volReadout"></div>
    <div class="chart-wrap"><canvas id="volCanvas" height="250"></canvas></div>
    <div class="caption" id="volCaption"></div>
  </section>

  <!-- Panel: market regime (phase scatter of vol vs price) -->
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>Market regime — where the state sits</h2>
        <div class="thesis">Each recent day plotted by realised volatility (x) and price (y) —
          brighter is more recent, so you see the trajectory. Four states split at the median:
          low/high price against low/high volatility.</div>
      </div>
      <div class="legend">
        <span><span class="swatch" style="background:var(--obs)"></span>low price · low vol</span>
        <span><span class="swatch" style="background:var(--price)"></span>high price · low vol</span>
        <span><span class="swatch" style="background:var(--residual)"></span>low price · high vol</span>
        <span><span class="swatch" style="background:var(--warn)"></span>high price · high vol</span>
      </div>
    </div>
    <div class="fuel-readout" id="rgReadout"></div>
    <div class="chart-wrap"><canvas id="rgCanvas" height="300"></canvas></div>
    <div class="caption" id="rgCaption"></div>
  </section>

  </div>

*/
