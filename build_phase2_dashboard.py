"""Build the Phase-II runtime dashboard — interactive.

Runs the Phase-II execution graph and emits a self-contained interactive
HTML dashboard. No plotting library, no JS framework, no network — data is
embedded as JSON and rendered to <canvas> by a small vanilla-JS engine.

Features:
  - equity chart with the full strategy family (V7.10 line + manifolds +
    sleeves + S&P 500), each curve toggle-on/off with a colour picker
  - comparison table — Total return / CAGR / vol / Sharpe / Sortino /
    Calmar / Max DD / Corr SPY for every series
  - mouse time-brush (drag to zoom all charts; double-click / Reset to undo)
  - governance-zone colour bands behind the time-series panels
  - asset-allocation panel (stacked exposure of the 13 futures + CASH)
  - index explorer — toggle any Layer 3/4/5/5A index, pick its colour
  - the new index charts + crisis-window marks

    agora/bin/python build_phase2_dashboard.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    UNIVERSE, EngineConfig, compute_weights, equal_weight_signal, evaluate,
    load_partner_xlsx)
from polyagora.governance.moat import MoatStackBase
from polyagora.regression import CRISIS_WINDOWS, RegressionGate, metrics
from polyagora.runtime import ExecutionGraph

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
V710_DIR = ROOT / "polyagora_v710_outputs"
V75_DIR = ROOT / "polyagora_v75_outputs"
OUTPUT = ROOT / "polyagora_phase2_outputs"

# Strategy family for the equity chart + comparison table.
# (key, label, colour, source, default-on)  — source: csv name / PHASE2 / EQUAL / SP500
FAMILY = [
    ("phase2",        "Phase-II runtime (moat + L3/4/5/5A)", "#3a7bd5", "PHASE2", True),
    ("v710",          "V7.10 · Strategy Sleeve Registry",    "#111111", "returns_v710.csv", True),
    ("v79",           "V7.9 · governed defensive rotation",  "#2e8b57", "returns_v79.csv", False),
    ("v78_add",       "V7.8-ADD · asset-level ADD-lite",     "#5c8a3a", "returns_v78_add.csv", False),
    ("v76",           "V7.6a · meta-steered governance",     "#8d6e63", "returns_v76.csv", False),
    ("v74d_q",        "M1: V7.4d_q · V7 manifold",           "#9c27b0", "returns_v74d_q.csv", False),
    ("momentum_12_1", "M2: Momentum 12-1",                   "#d56fa8", "returns_momentum_12_1.csv", False),
    ("defensive",     "M3: Defensive manifold",              "#138d8d", "returns_defensive.csv", False),
    ("cash",          "M4: Cash",                            "#bdbdbd", "returns_cash.csv", False),
    ("bond_trend",    "Bond-trend sleeve (ADMITTED)",        "#e07b00", "returns_bond_trend.csv", False),
    ("mr_sleeve",     "MR-sleeve (REJECTED)",                "#c0392b", "returns_mr_sleeve.csv", False),
    ("equal_weight",  "Equal-weight · 1/N",                  "#7b3ad5", "EQUAL", False),
    ("sp500",         "S&P 500 · buy-and-hold",              "#d9a000", "SP500", True),
]


def _arr(s: pd.Series) -> list:
    return [round(float(x), 4) if np.isfinite(x) else None for x in s]


def _equity(returns: pd.Series, dates: pd.DatetimeIndex) -> list:
    return _arr((1.0 + returns.reindex(dates).fillna(0.0)).cumprod())


def _csv_returns(path: Path) -> pd.Series:
    c = pd.read_csv(path, nrows=0).columns[0]
    return pd.read_csv(path, parse_dates=[c]).set_index(c).iloc[:, 0]


def _row_metrics(returns: pd.Series, dates, spy: pd.Series) -> dict:
    r = returns.reindex(dates).dropna()
    m = metrics(r)
    eq = (1.0 + r).cumprod()
    j = pd.concat([r, spy], axis=1, join="inner").dropna()
    return {
        "total": float(eq.iloc[-1] - 1.0) if len(eq) else 0.0,
        "cagr": m["cagr"], "vol": float(r.std() * math.sqrt(252)),
        "sharpe": m["sharpe"], "sortino": m["sortino"], "calmar": m["calmar"],
        "max_dd": m["max_dd"],
        "corr_spy": float(j.iloc[:, 0].corr(j.iloc[:, 1])) if len(j) > 30 else float("nan"),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(INPUT)
    macro = pd.read_csv(MARKET, parse_dates=["date"]).set_index("date")
    moat = MoatStackBase(V710_DIR / "weights_v710.csv", macro, UNIVERSE)
    graph = ExecutionGraph(macro, UNIVERSE, base_provider=moat)
    panel = graph.run_full(data.realized_pnl)
    candidate = evaluate(panel, data.forward_pnl).returns
    trace = graph.trace_frame()
    dates = trace.index
    reference = _csv_returns(V710_DIR / "returns_v710.csv")
    spy = macro["SPY"].pct_change().rename("SPY")
    gate = RegressionGate(reference, spy=spy).evaluate(candidate)
    cm, rm = metrics(candidate), metrics(reference)
    print(f"[dashboard] graph run: {len(trace)} bars, "
          f"§12.2 {'PASS' if gate.passed else 'FAIL'} "
          f"{sum(c.passed for c in gate.checks)}/{len(gate.checks)}")

    # --- strategy-family returns -------------------------------------------
    ew = evaluate(compute_weights(data, equal_weight_signal, EngineConfig()),
                  data.forward_pnl).returns
    fam_returns: dict[str, pd.Series] = {}
    for key, _lab, _col, src, _on in FAMILY:
        if src == "PHASE2":
            fam_returns[key] = candidate
        elif src == "EQUAL":
            fam_returns[key] = ew
        elif src == "SP500":
            p = V75_DIR / "returns_sp500.csv"
            if p.exists():
                fam_returns[key] = _csv_returns(p)
        else:
            p = V710_DIR / src
            if p.exists():
                fam_returns[key] = _csv_returns(p)

    trace["R"] = 0.5 * (trace["R_reentry"] + trace["R_persist"])
    crisis = [{"name": n, "a": int(dates.searchsorted(pd.Timestamp(a))),
               "b": int(dates.searchsorted(pd.Timestamp(b)))}
              for n, (a, b) in CRISIS_WINDOWS.items()]

    # --- per-curve metrics for the comparison table (rendered in JS) -------
    def _num(x):
        return round(float(x), 5) if np.isfinite(x) else None

    metrics_by_key = {k: {f: _num(v) for f, v in
                          _row_metrics(fam_returns[k], dates, spy).items()}
                      for k, _l, _c, _s, _o in FAMILY if k in fam_returns}

    DATA = {
        "dates": [d.strftime("%Y-%m-%d") for d in dates],
        "zones": trace["zone"].astype(str).tolist(),
        "vaidm": trace["vaidm"].astype(str).tolist(),
        "series": {k: _arr(trace[k]) for k in
                   ["C_t", "F_t", "P_t", "R", "R_reentry", "R_persist",
                    "erq_book", "mrtp", "f_t", "beta_t", "gross"]},
        "equity": {k: _equity(s, dates) for k, s in fam_returns.items()},
        "alloc": {"assets": list(UNIVERSE) + ["CASH"],
                  "w": {a: _arr(panel[a]) for a in list(UNIVERSE) + ["CASH"]}},
        "crisis": crisis,
        "family": [[k, lab, col, on] for k, lab, col, _s, on in FAMILY
                   if k in fam_returns],
        "metrics": metrics_by_key,
    }

    gate_rows = "".join(
        f'<tr><td>{c.metric}</td><td>{c.reference:.4f}</td>'
        f'<td>{c.candidate:.4f}</td><td class="{ "ok" if c.passed else "no" }">'
        f'{"PASS" if c.passed else "FAIL"}</td></tr>' for c in gate.checks)

    head = """<!doctype html><html><head><meta charset="utf-8">
<title>PolyAgora Phase-II — Runtime Dashboard</title><style>
body{font:13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;
background:#f4f5f7;color:#222}
.wrap{max-width:1240px;margin:0 auto;padding:20px}
h1{font-size:21px;margin:0 0 2px;color:#1a3a5c}
.sub{color:#777;margin-bottom:14px;font-size:12px}
.card{background:#fff;border:1px solid #e3e5e8;border-radius:7px;
padding:12px 16px;margin-bottom:12px}
.ct{font-size:11.5px;font-weight:700;color:#1a3a5c;margin-bottom:4px}
canvas{width:100%;height:auto;display:block;cursor:crosshair}
table{border-collapse:collapse;width:100%;font-size:12px}
td,th{padding:3px 9px;border-bottom:1px solid #eee;text-align:right}
td:first-child,th:first-child{text-align:left;color:#444}
th{color:#888;font-weight:600;border-bottom:2px solid #e3e5e8}
#cmp th{cursor:pointer;user-select:none;white-space:nowrap}
#cmp th:hover{color:#1a3a5c}
.sh{font-weight:600;color:#1a3a5c}
.ok{color:#2e8b57;font-weight:600}.no{color:#c0392b;font-weight:600}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px}
.flex{display:flex;gap:12px}.flex .card{flex:1}
.bar{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.bar label{display:flex;align-items:center;gap:4px;color:#555}
.bar input{font:inherit;padding:3px 5px;border:1px solid #c3c7cc;border-radius:4px}
button{font:inherit;padding:5px 12px;border:1px solid #c3c7cc;border-radius:5px;
background:#fff;cursor:pointer}button:hover{background:#eef}
.ctl{display:flex;flex-wrap:wrap;gap:5px 14px;margin-top:8px;font-size:11px}
.ctl label{display:flex;align-items:center;gap:4px;color:#444}
.ctl input[type=color]{width:22px;height:16px;padding:0;border:1px solid #ccc}
#win{color:#1a3a5c;font-weight:600}
</style></head><body><div class="wrap">
<h1>PolyAgora Phase-II — Runtime Dashboard</h1>"""

    header = f"""<div class="sub">Six-layer runtime · moat base (V7.10) +
Layers 3/4/5/5A · {DATA['dates'][0]} → {DATA['dates'][-1]} · {len(dates)} bars</div>
<div class="card"><div class="ct">&sect;12.2 MOAT GATE &nbsp;
<span class="{'ok' if gate.passed else 'no'}">{'PASS' if gate.passed else 'FAIL'}
&mdash; {sum(c.passed for c in gate.checks)}/{len(gate.checks)}</span></div>
<table><tr><th>check</th><th>V7.10</th><th>Phase-II</th><th></th></tr>
{gate_rows}</table></div>
<div class="bar"><button onclick="resetZoom()">Reset zoom</button>
<label>Start <input type="date" id="d0"></label>
<label>End <input type="date" id="d1"></label>
<span>Window: <span id="win"></span></span>
<span class="sub" style="margin:0">drag a chart to zoom &middot; or set dates &middot; double-click resets</span>
</div>
<div class="card"><div class="ct">Equity — growth of $1 from the window start (log scale)</div>
<canvas id="eq"></canvas><div class="ctl" id="eq_ctl"></div></div>
<div class="card"><div class="ct">Comparison table — selected curves, full-sample metrics
(rows follow the equity-chart toggles · click a column header to sort)</div>
<table id="cmp"><thead><tr id="cmp_head"></tr></thead>
<tbody id="cmp_body"></tbody></table></div>"""

    panel_html = """
<div class="card"><div class="ct">Asset allocation — exposure of the 13 futures + CASH</div>
<canvas id="alloc"></canvas></div>
<div class="card"><div class="ct">Index explorer — toggle indexes, pick colours,
overlay vs reference indexes (per-series normalised over the visible window)</div>
<canvas id="explorer"></canvas><div class="ctl" id="explorer_ctl"></div></div>
<div class="card"><div class="ct">Governance zone (5-mode) &middot; VAIDM class</div>
<canvas id="zone"></canvas><canvas id="vaidm"></canvas></div>
<div class="card"><div class="ct">Layer 5 — Recoverability geometry (C / F / P)</div>
<canvas id="geom"></canvas></div>
<div class="card"><div class="ct">Layer 5 — Recoverability R_t</div>
<canvas id="rec"></canvas></div>
<div class="card"><div class="ct">Layer 5A — Exposure Recoverability Quality</div>
<canvas id="erq"></canvas></div>
<div class="card"><div class="ct">Layer 3 — MRTP convexity score</div>
<canvas id="mrtp"></canvas></div>
<div class="card"><div class="ct">Layer 4 — Dynamic Kelly leverage f_t</div>
<canvas id="kelly"></canvas></div>
<div class="sub">Crisis windows (GFC / COVID / 2022) shaded · zone bands behind
time-series panels · generated by build_phase2_dashboard.py, no dependencies.</div>
</div>"""

    html = (head + header + panel_html + "<script>\nconst DATA="
            + json.dumps(DATA) + ";\n" + _JS + "\n</script></body></html>")
    out = OUTPUT / "phase2_dashboard.html"
    out.write_text(html, encoding="utf-8")
    print(f"[dashboard] wrote {out}  ({out.stat().st_size // 1024} KB)")


_JS = r"""
const D=DATA, N=D.dates.length;
let view={a:0,b:N-1};
const ZC={LOCAL_STAR:'#2e8b57',TRANSITION:'#3a7bd5',LEAST_BAD:'#d99a00',
          BUFFER:'#888888',BOUNDARY:'#c0392b'};
const VC={BENIGN:'#2e8b57',ELEVATED:'#d9c000',HIGH_STRESS:'#e07b00',RUPTURE:'#c0392b'};
const ALC=['#3a7bd5','#e07b00','#2e8b57','#c0392b','#7b3ad5','#138d8d','#d9a000',
           '#8d6e63','#d56fa8','#5c8a3a','#1a3a5c','#9c27b0','#00897b','#bdbdbd'];
const W=1140, L=58, R=250, T=24, B=22;

function ser(k){
  if(D.equity[k]) return D.equity[k];
  if(D.series[k]) return D.series[k];
  return null;
}
function xMap(i,n){ return L+((i-view.a)/Math.max(n-1,1))*(W-L-R); }
function xInv(x,n){ return view.a+(x-L)/(W-L-R)*Math.max(n-1,1); }

function bg(cx,H,zoneBands){
  const n=view.b-view.a+1;
  if(zoneBands){ let i=view.a;
    while(i<=view.b){ let j=i;
      while(j+1<=view.b && D.zones[j+1]===D.zones[i]) j++;
      cx.fillStyle=ZC[D.zones[i]]||'#ccc'; cx.globalAlpha=0.10;
      const x0=xMap(i,n), x1=xMap(j,n);
      cx.fillRect(x0,T,Math.max(x1-x0,0.5),H-T-B); i=j+1; }
    cx.globalAlpha=1; }
  for(const c of D.crisis){
    if(c.b<view.a||c.a>view.b) continue;
    const x0=xMap(Math.max(c.a,view.a),n), x1=xMap(Math.min(c.b,view.b),n);
    cx.fillStyle='#c0392b'; cx.globalAlpha=0.085;
    cx.fillRect(x0,T,Math.max(x1-x0,0.5),H-T-B); cx.globalAlpha=1;
    cx.fillStyle='#c0392b'; cx.font='9px sans-serif';
    cx.fillText(c.name,x0+3,T+10); }
}
function xticks(cx,H,n){
  let py=-1;
  for(let i=Math.max(view.a,1);i<=view.b;i++){
    const yr=+D.dates[i].slice(0,4);
    if(yr!==py && yr%2===0){ const x=xMap(i,n);
      cx.strokeStyle='#eee';cx.beginPath();cx.moveTo(x,T);cx.lineTo(x,H-B);cx.stroke();
      cx.fillStyle='#999';cx.font='9px sans-serif';cx.textAlign='center';
      cx.fillText(yr,x,H-9); }
    py=yr; }
  cx.textAlign='left';
}
function legend(cx,items){
  items.forEach((it,k)=>{ const y=T+7+k*13;
    cx.strokeStyle=it.color;cx.lineWidth=2.5;cx.beginPath();
    cx.moveTo(W-R+6,y);cx.lineTo(W-R+22,y);cx.stroke();cx.lineWidth=1;
    cx.fillStyle='#444';cx.font='9.5px sans-serif';
    cx.fillText(it.label.length>40?it.label.slice(0,39)+'…':it.label,W-R+26,y+3); });
}
function drawTS(p){
  const cv=p.canvas, cx=cv.getContext('2d'), H=cv.height, n=view.b-view.a+1;
  cx.clearRect(0,0,W,H); bg(cx,H,p.zoneBands);
  const on=p.series.filter(s=>s.on!==false && ser(s.key));
  const logS=(p.yMode==='log'), norm=(p.yMode==='norm');
  let y0=p.y0,y1=p.y1;
  if(p.yMode==='auto'||logS){ y0=1e18;y1=-1e18;
    for(const s of on){ const a=ser(s.key);
      const base=p.rebase?(a[view.a]||1):1;
      for(let i=view.a;i<=view.b;i++){ let v=a[i];
        if(v==null||(logS&&v<=0)) continue;
        v=v/base;
        if(v<y0)y0=v; if(v>y1)y1=v; } }
    if(y0>y1){y0=0;y1=1;}
    if(logS){ y0=Math.log(y0*0.97); y1=Math.log(y1*1.03); }
    else{ const pad=(y1-y0)*0.06||1; y0-=pad; y1+=pad; } }
  if(norm){ y0=0; y1=1; }
  // y gridlines
  cx.strokeStyle='#eee';cx.font='9px sans-serif';
  for(let f=0;f<=1;f+=0.5){ const y=T+(1-f)*(H-T-B);
    cx.beginPath();cx.moveTo(L,y);cx.lineTo(W-R,y);cx.stroke();
    let lab=y0+f*(y1-y0); if(logS) lab=Math.exp(lab);
    cx.fillStyle='#999';cx.textAlign='right';
    cx.fillText(lab.toFixed(2),L-5,y+3); }
  cx.textAlign='left';
  xticks(cx,H,n);
  for(const ref of (p.refs||[])){ const y=T+(1-(ref.v-y0)/(y1-y0))*(H-T-B);
    cx.strokeStyle=ref.color;cx.setLineDash([4,3]);cx.beginPath();
    cx.moveTo(L,y);cx.lineTo(W-R,y);cx.stroke();cx.setLineDash([]); }
  for(const s of on){
    const a=ser(s.key); let mn=0,mx=1;
    const base=p.rebase?(a[view.a]||1):1;
    if(norm){ mn=1e18;mx=-1e18;
      for(let i=view.a;i<=view.b;i++){ const v=a[i];
        if(v!=null){ if(v<mn)mn=v; if(v>mx)mx=v; } }
      if(mx-mn<1e-9) mx=mn+1; }
    cx.strokeStyle=s.color; cx.lineWidth=1.2; cx.beginPath(); let st=false;
    for(let i=view.a;i<=view.b;i++){ let v=a[i];
      if(v==null||(logS&&v<=0)){st=false;continue;}
      v=v/base;
      if(norm) v=(v-mn)/(mx-mn);
      const t=logS?(Math.log(v)-y0)/(y1-y0):(v-y0)/(y1-y0);
      const x=xMap(i,n), y=T+(1-t)*(H-T-B);
      if(st)cx.lineTo(x,y); else{cx.moveTo(x,y);st=true;} }
    cx.stroke(); cx.lineWidth=1;
  }
  legend(cx,on);
}
function drawAlloc(p){
  const cv=p.canvas, cx=cv.getContext('2d'), H=cv.height, n=view.b-view.a+1;
  cx.clearRect(0,0,W,H); bg(cx,H,false);
  const A=D.alloc.assets, w=D.alloc.w;
  let lo=0,hi=0;
  for(let i=view.a;i<=view.b;i++){ let pos=0,neg=0;
    for(const a of A){ const v=w[a][i]||0; if(v>=0)pos+=v; else neg+=v; }
    if(pos>hi)hi=pos; if(neg<lo)lo=neg; }
  hi=Math.max(hi,1); const y=v=>T+(1-(v-lo)/(hi-lo))*(H-T-B);
  cx.strokeStyle='#eee';cx.beginPath();cx.moveTo(L,y(0));cx.lineTo(W-R,y(0));cx.stroke();
  xticks(cx,H,n);
  const posBase=new Array(N).fill(0), negBase=new Array(N).fill(0);
  A.forEach((a,k)=>{ cx.fillStyle=ALC[k%ALC.length]; cx.globalAlpha=0.9;
    cx.beginPath(); const top=[],bot=[];
    for(let i=view.a;i<=view.b;i++){ const v=w[a][i]||0;
      const b0=v>=0?posBase[i]:negBase[i], b1=b0+v;
      top.push([xMap(i,n),y(b1)]); bot.push([xMap(i,n),y(b0)]);
      if(v>=0)posBase[i]=b1; else negBase[i]=b1; }
    top.forEach((q,j)=>j?cx.lineTo(q[0],q[1]):cx.moveTo(q[0],q[1]));
    for(let j=bot.length-1;j>=0;j--)cx.lineTo(bot[j][0],bot[j][1]);
    cx.closePath();cx.fill(); });
  cx.globalAlpha=1;
  legend(cx,A.map((a,k)=>({label:a,color:ALC[k%ALC.length]})));
}
function drawRibbon(p){
  const cv=p.canvas, cx=cv.getContext('2d'), H=cv.height, n=view.b-view.a+1;
  cx.clearRect(0,0,W,H);
  const vals=D[p.key], cmap=p.cmap;
  let i=view.a;
  while(i<=view.b){ let j=i;
    while(j+1<=view.b && vals[j+1]===vals[i]) j++;
    cx.fillStyle=cmap[vals[i]]||'#ccc';
    const x0=xMap(i,n),x1=xMap(j,n);
    cx.fillRect(x0,4,Math.max(x1-x0,0.6),H-16); i=j+1; }
  cx.font='9px sans-serif'; let k=0;
  for(const key in cmap){ const lx=L+118*k;
    cx.fillStyle=cmap[key];cx.fillRect(lx,H-9,9,7);
    cx.fillStyle='#666';cx.fillText(key,lx+12,H-3); k++; }
}
let PANELS=[];
function draw(p){ p.kind==='alloc'?drawAlloc(p):p.kind==='ribbon'?drawRibbon(p):drawTS(p); }
function drawAll(){ PANELS.forEach(draw);
  document.getElementById('win').textContent=
    D.dates[view.a]+'  →  '+D.dates[view.b]+'  ('+(view.b-view.a+1)+' bars)'; }
function dateIdx(s){ for(let i=0;i<N;i++) if(D.dates[i]>=s) return i; return N-1; }
function setView(a,b){
  a=Math.max(0,Math.min(a,N-1)); b=Math.max(0,Math.min(b,N-1));
  if(b-a<3) return;
  view={a:a,b:b};
  const d0=document.getElementById('d0'), d1=document.getElementById('d1');
  if(d0){ d0.value=D.dates[a]; d1.value=D.dates[b]; }
  drawAll();
}
function resetZoom(){ setView(0,N-1); }

function brush(p){
  const cv=p.canvas; let x0=null;
  function mx(e){ const r=cv.getBoundingClientRect();
    return (e.clientX-r.left)*(cv.width/r.width); }
  cv.addEventListener('mousedown',e=>{x0=mx(e);});
  cv.addEventListener('mousemove',e=>{ if(x0==null)return; draw(p);
    const x1=mx(e), c=cv.getContext('2d'); c.fillStyle='#3a7bd5';c.globalAlpha=0.18;
    c.fillRect(Math.min(x0,x1),T,Math.abs(x1-x0),cv.height-T-B);c.globalAlpha=1; });
  window.addEventListener('mouseup',e=>{ if(x0==null)return;
    const x1=mx(e), n=view.b-view.a+1;
    if(Math.abs(x1-x0)>6){
      let a=Math.round(xInv(Math.min(x0,x1),n)), b=Math.round(xInv(Math.max(x0,x1),n));
      setView(a,b); }
    x0=null; });
  cv.addEventListener('dblclick',resetZoom);
}
function setup(id,h,kind,opt){
  const cv=document.getElementById(id); cv.width=W; cv.height=h;
  const p=Object.assign({canvas:cv,kind:kind},opt); PANELS.push(p);
  if(kind!=='ribbon') brush(p); return p;
}
function buildControls(panel,divId,hook){
  const ctl=document.getElementById(divId);
  panel.series.forEach(s=>{ if(!ser(s.key)) return;
    const lab=document.createElement('label');
    const cb=document.createElement('input'); cb.type='checkbox'; cb.checked=s.on!==false;
    cb.onchange=()=>{ s.on=cb.checked; draw(panel); if(hook)hook(); };
    const cl=document.createElement('input'); cl.type='color'; cl.value=s.color;
    cl.oninput=()=>{ s.color=cl.value; draw(panel); if(hook)hook(); };
    lab.appendChild(cb); lab.appendChild(cl);
    lab.appendChild(document.createTextNode(' '+s.label)); ctl.appendChild(lab); });
}
// --- comparison table — sortable, follows the equity-chart toggles --------
const COLS=[{k:'label',n:'Series',num:false},
  {k:'total',n:'Total return',num:true,pct:true},
  {k:'cagr',n:'CAGR',num:true,pct:true},{k:'vol',n:'Ann. vol',num:true,pct:true},
  {k:'sharpe',n:'Sharpe',num:true},{k:'sortino',n:'Sortino',num:true},
  {k:'calmar',n:'Calmar',num:true},{k:'max_dd',n:'Max DD',num:true,pct:true},
  {k:'corr_spy',n:'Corr SPY',num:true}];
let sortState={k:'sharpe',dir:-1};
function fmtCell(v,pct){
  if(v==null||!isFinite(v)) return '—';
  return pct?(v*100).toFixed(1)+'%':v.toFixed(2);
}
function renderTable(){
  const hd=document.getElementById('cmp_head'); hd.innerHTML='';
  COLS.forEach(c=>{ const th=document.createElement('th');
    th.textContent=c.n+(sortState.k===c.k?(sortState.dir<0?' ▼':' ▲'):'');
    th.onclick=()=>{ if(sortState.k===c.k) sortState.dir*=-1;
      else{ sortState.k=c.k; sortState.dir=c.num?-1:1; } renderTable(); };
    hd.appendChild(th); });
  let rows=EQ.series.filter(s=>s.on!==false && D.metrics[s.key])
    .map(s=>Object.assign({label:s.label,color:s.color},D.metrics[s.key]));
  const sk=sortState.k, dir=sortState.dir;
  rows.sort((a,b)=>{
    if(sk==='label') return dir*a.label.localeCompare(b.label);
    let x=a[sk],y=b[sk];
    const xb=(x==null||!isFinite(x)), yb=(y==null||!isFinite(y));
    if(xb&&yb)return 0; if(xb)return 1; if(yb)return -1;
    return x<y?-dir:x>y?dir:0; });
  document.getElementById('cmp_body').innerHTML=rows.map(r=>
    '<tr><td><span class="dot" style="background:'+r.color+'"></span>'+r.label
    +'</td>'+COLS.slice(1).map(c=>'<td'+(c.k==='sharpe'?' class="sh"':'')
    +'>'+fmtCell(r[c.k],c.pct)+'</td>').join('')+'</tr>').join('');
}
// --- panels ---------------------------------------------------------------
const EQ=setup('eq',300,'ts',{zoneBands:true,yMode:'log',rebase:true,
  series:D.family.map(f=>({key:f[0],label:f[1],color:f[2],on:f[3]}))});
setup('alloc',250,'alloc',{});
const EXP=setup('explorer',250,'ts',{zoneBands:true,yMode:'norm',series:[
  {key:'C_t',label:'C_t',color:'#2e8b57',on:true},
  {key:'F_t',label:'F_t',color:'#c0392b',on:true},
  {key:'P_t',label:'P_t',color:'#e07b00',on:false},
  {key:'R',label:'R',color:'#7b3ad5',on:false},
  {key:'erq_book',label:'ERQ',color:'#138d8d',on:false},
  {key:'mrtp',label:'MRTP',color:'#1a3a5c',on:false},
  {key:'f_t',label:'f_t',color:'#3a7bd5',on:false},
  {key:'beta_t',label:'beta',color:'#8d6e63',on:false},
  {key:'phase2',label:'Phase-II equity',color:'#000000',on:true},
  {key:'sp500',label:'S&P 500',color:'#d9a000',on:true},
  {key:'momentum_12_1',label:'Momentum',color:'#d56fa8',on:false}]});
setup('zone',44,'ribbon',{key:'zones',cmap:ZC});
setup('vaidm',44,'ribbon',{key:'vaidm',cmap:VC});
setup('geom',186,'ts',{zoneBands:true,yMode:'fixed',y0:0,y1:1,series:[
  {key:'C_t',label:'C_t',color:'#2e8b57'},{key:'F_t',label:'F_t',color:'#c0392b'},
  {key:'P_t',label:'P_t',color:'#e07b00'}]});
setup('rec',186,'ts',{zoneBands:true,yMode:'fixed',y0:0,y1:1,series:[
  {key:'R_reentry',label:'R_reentry',color:'#3a7bd5'},
  {key:'R_persist',label:'R_persist',color:'#7b3ad5'},
  {key:'R',label:'R mean',color:'#111111'}]});
setup('erq',186,'ts',{zoneBands:true,yMode:'fixed',y0:0,y1:1,series:[
  {key:'erq_book',label:'ERQ',color:'#7b3ad5'}]});
setup('mrtp',186,'ts',{zoneBands:true,yMode:'fixed',y0:-0.5,y1:1.5,
  refs:[{v:0.65,color:'#2e8b57'},{v:0.25,color:'#c0392b'}],
  series:[{key:'mrtp',label:'MRTP',color:'#138d8d'}]});
setup('kelly',186,'ts',{zoneBands:true,yMode:'fixed',y0:1,y1:1.26,
  refs:[{v:1.25,color:'#c0392b'}],
  series:[{key:'f_t',label:'f_t',color:'#3a7bd5'}]});
const D0=document.getElementById('d0'), D1=document.getElementById('d1');
D0.min=D1.min=D.dates[0]; D0.max=D1.max=D.dates[N-1];
D0.value=D.dates[0]; D1.value=D.dates[N-1];
D0.onchange=D1.onchange=()=>setView(dateIdx(D0.value),dateIdx(D1.value));
buildControls(EQ,'eq_ctl',renderTable);
buildControls(EXP,'explorer_ctl');
renderTable();
drawAll();
"""


if __name__ == "__main__":
    main()
