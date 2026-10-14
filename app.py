import json,subprocess,sys,tempfile
from datetime import time,timedelta
from pathlib import Path
import numpy as np,pandas as pd,plotly.express as px,streamlit as st
R=Path(__file__).resolve().parent; D=R/"final_dataset"
EX=["binance","coinbase","kucoin","bitfinex","bybit","htx","cryptocom"]
LABEL=dict(zip(EX,["Binance","Coinbase","KuCoin","Bitfinex","Bybit","HTX","Crypto.com"]))
SC={"base_taker_buf":"Base taker + buffer","base_taker_nobuf":"Base taker, no buffer","maker_both_legs":"Maker + buffer","hyp_fee0.05_buf0.01":"Hypothetical low fee","hyp_fee0.05_buf0.01_no_transfers":"Hypothetical, no transfers","hyp_fee0.05_buf0.01_inv2x":"Hypothetical, 2× inventory","hyp_fee0.02_buf0.01":"Hypothetical 0.02% fee","hyp_fee0.00_buf0.00":"Hypothetical zero fee"}
st.set_page_config(page_title="Aster | Arbitrage Research",page_icon="◈",layout="wide")
st.markdown("""<style>.block-container{padding-top:1.25rem;max-width:1500px}.hero{padding:1rem 1.3rem;border:1px solid #28504f;border-radius:18px;background:linear-gradient(110deg,#132c35,#111b2c 60%,#211f38);margin-bottom:1rem}.hero h1{margin:.3rem 0;font-size:2rem;letter-spacing:-.04em}.hero p{color:#aebbd0}.kicker{color:#72e1d0;letter-spacing:.17em;text-transform:uppercase;font-size:.72rem;font-weight:700}</style>""",unsafe_allow_html=True)
@st.cache_data(show_spinner="Loading project data…")
def load():
 c=["ts","pair","exchange","quote_ccy","close","volume","close_usdt_equiv","is_filled","is_stale","is_outlier","is_zero_volume","tradable","taker_fee_pct","maker_fee_pct"]
 d=pd.read_csv(D/"milp_master.csv",usecols=c,parse_dates=["ts"]);d["ts"]=pd.to_datetime(d.ts,utc=True);return d
@st.cache_data
def getres():return json.loads((R/"results_v2.json").read_text(encoding="utf-8"))
def cash(x):return " $" + f"{x:,.2f}"
def subset(d,p,s,e):
 lo=pd.Timestamp.combine(s,time.min).tz_localize("UTC");hi=pd.Timestamp.combine(e+timedelta(days=1),time.min).tz_localize("UTC")
 return d[(d.pair==p)&(d.ts>=lo)&(d.ts<hi)].copy()
def screen(d,fee,buf,cap,ceil,floor):
 d=d[d.ts.dt.minute.isin([0,30])&(d.ts.dt.second==0)]
 if d.empty:return pd.DataFrame(),pd.DataFrame()
 p=d.pivot_table(index="ts",columns="exchange",values="close_usdt_equiv",aggfunc="last");v=d.pivot_table(index="ts",columns="exchange",values="volume",aggfunc="last");ok=d.pivot_table(index="ts",columns="exchange",values="tradable",aggfunc="last").fillna(False);fees=d.pivot_table(index="ts",columns="exchange",values="taker_fee_pct",aggfunc="last");rows=[]
 for b in [x for x in EX if x in p]:
  for s in [x for x in EX if x in p and x!=b]:
   valid=ok[b].astype(bool)&ok[s].astype(bool);gross=(p[s]/p[b]-1)*100;fee_cost=(fees[b]+fees[s]) if fee is None else 2*fee;net=gross-fee_cost-2*buf;valid &= net.ge(floor)&p[b].gt(0)
   if valid.any():
    size=np.minimum(ceil,np.minimum(v.loc[valid,b]*p.loc[valid,b],v.loc[valid,s]*p.loc[valid,s])*cap/100)
    rows.append(pd.DataFrame({"UTC time":valid.index[valid],"Buy venue":LABEL[b],"Sell venue":LABEL[s],"Net edge (%)":net[valid].values,"Illustrative edge":size.values*net[valid].values/100,"Notional":size.values}))
 if not rows:return pd.DataFrame(),pd.DataFrame()
 o=pd.concat(rows,ignore_index=True).sort_values("Net edge (%)",ascending=False);return o,o.loc[o.groupby("UTC time")["Net edge (%)"].idxmax()].sort_values("UTC time")
def run(day,scenario,limit):
 d=load();one=d[d.ts.dt.date==day]
 with tempfile.TemporaryDirectory() as t:
  t=Path(t);src=t/"m.csv";out=t/"r.json";one.to_csv(src,index=False)
  cmd=[sys.executable,str(R/"milp_solver_v2.py"),"--master",str(src),"--params",str(R/"params.csv"),"--grid","30min","--days","1","--time-limit",str(limit),"--gap","0.01","--scenarios",scenario,"--out",str(out)]
  z=subprocess.run(cmd,cwd=R,capture_output=True,text=True,timeout=limit+90)
  if z.returncode or not out.exists():return None,z.stderr or z.stdout
  return json.loads(out.read_text(encoding="utf-8")),z.stdout
df=load();ev=getres();runs=ev.get("runs",[]);days=sorted(df.ts.dt.date.unique())
with st.sidebar:
 st.markdown("### ◈ ASTER");st.caption("Operations research · Financial engineering")
 page=st.radio("Workspace",["Overview","Opportunity lab","MILP optimizer","Data & methodology"],label_visibility="collapsed")
 st.divider();pair=st.selectbox("Asset market",["BTC/USDT","ETH/USDT"])
 span=st.date_input("UTC study window",value=(days[0],days[-1]),min_value=days[0],max_value=days[-1])
 if isinstance(span,(tuple,list)) and len(span)==2:first,last=span
 elif isinstance(span,(tuple,list)) and len(span)==1:first=last=span[0]
 else:first=last=span
 if first>last:first,last=last,first
 st.divider();st.caption("LOCAL DATA · 02–08 OCT 2026")
d=subset(df,pair,first,last);base=next((x for x in runs if x["scenario"]["name"]=="base_taker_buf"),{})
st.markdown(f'<div class="hero"><div class="kicker">ASTER · RESEARCH TERMINAL · LOCAL / MILP</div><h1>{page}</h1><p>{pair} · {first:%d %b} – {last:%d %b %Y} UTC · 7 exchanges</p></div>',unsafe_allow_html=True)
if page=="Overview":
 t=base.get("per_day",[]);positive_case=next((x for x in runs if x["scenario"]["name"]=="hyp_fee0.05_buf0.01_no_transfers"),{});a,b,c,e,f=st.columns(5);a.metric("Audited baseline P&L",cash(base.get("total_profit_usdt",0)),"7-day MILP",border=True);b.metric("Modeled profit · hypothetical",cash(positive_case.get("total_profit_usdt",0)),"0.05% fee · 0.01% buffer · no transfers",border=True);c.metric("Market observations",f"{len(d):,}","filtered",border=True);e.metric("UTC coverage",f"{df.ts.nunique()/10080:.1%}","10,080-minute grid",border=True);f.metric("Solve time",f"{np.mean([x['runtime_sec'] for x in t]):.2f}s","per day",border=True)
 l,r=st.columns([1.6,1])
 with l:
  st.subheader("Cross-exchange price path");x=d[d.ts.dt.minute.isin([0,30])]
  if len(x):
   f=px.line(x,x="ts",y="close_usdt_equiv",color="exchange",labels={"ts":"UTC time","close_usdt_equiv":"USDT-equivalent price","exchange":"Venue"});st.plotly_chart(f,width="stretch",alt=f"{pair} close prices by exchange")
 with r:
  st.subheader("Final model finding");st.markdown("Base-fee MILP found **no positive net trades** in this sample. Spreads did not cover both trading fee legs, execution buffer, and inventory constraints.");st.metric("Baseline trades",str(sum(q["n_buy"]+q["n_sell"] for q in t)),f"{sum(q['replay_ok'] for q in t)}/{len(t)} windows replayed");st.caption("Candle closes are not simultaneous executable quotes.")
 table=[]
 for z in runs:
  ds=z["per_day"];sc=z["scenario"];table.append({"Scenario":SC.get(sc["name"],sc["name"]),"P&L":z["total_profit_usdt"],"Buys":sum(q["n_buy"] for q in ds),"Sells":sum(q["n_sell"] for q in ds),"Transfers":sum(q["n_transfers"] for q in ds),"Replay":"PASS" if z["all_replay_ok"] else "REVIEW","Optimal":f"{sum(q['status_code']==0 for q in ds)}/{len(ds)}"})
 st.subheader("Solver scenarios");st.dataframe(pd.DataFrame(table),hide_index=True,width="stretch",alt="Audited solver scenarios")
elif page=="Opportunity lab":
 st.markdown("Same-time spread screen. Inventory is assumed pre-positioned on both venues; transfers are not instantaneous.")
 venue_fees=st.checkbox("Use exchange-specific taker fees from project data",value=True);a,b,c,e=st.columns(4);fee=a.number_input("Flat fee per leg (%)",0.,2.,.1,.01,format="%.3f",disabled=venue_fees);buf=b.number_input("Buffer per leg (%)",0.,1.,.05,.01,format="%.3f");cap=c.number_input("Volume cap (%)",.1,50.,5.,.5);ceil=e.number_input("Notional limit ($)",5.,100000.,5000.,500.)
 floor=st.slider("Minimum net edge (%)",-.5,1.,0.,.01);o,best=screen(d,None if venue_fees else fee,buf,cap,ceil,floor);good=o[o["Net edge (%)"]>0] if len(o) else o
 a,b,c,e=st.columns(4);a.metric("Positive pairs",f"{len(good):,}",border=True);b.metric("Candidate timestamps",f"{good['UTC time'].nunique():,}" if len(good) else "0",border=True);c.metric("Best net edge",f"{o['Net edge (%)'].max():.4f}%" if len(o) else "—",border=True);e.metric("Screen edge sum",cash(good["Illustrative edge"].sum()) if len(good) else cash(0),"not modeled P&L",border=True)
 if len(best):
  l,r=st.columns([1.5,1])
  with l:
   f=px.line(best,x="UTC time",y="Net edge (%)",color_discrete_sequence=["#56D5C1"]);f.add_hline(y=0,line_dash="dash",line_color="#F17E91");st.plotly_chart(f,width="stretch",alt="Best net screened edge through time")
  with r:st.dataframe((good if len(good) else o).head(15),hide_index=True,width="stretch",height=360,alt="Highest screened venue pairs")
 if len(o):st.download_button("Download opportunities CSV",o.to_csv(index=False).encode(),file_name=f"{pair.replace('/','-')}-opportunities.csv",mime="text/csv")
 st.subheader("Inventory-aware benchmark results")
 bench=json.loads((R/"benchmark_results.json").read_text(encoding="utf-8")) if (R/"benchmark_results.json").exists() else None
 if bench:
  bm=bench["methods"]
  st.dataframe(pd.DataFrame([{"Method":"Greedy","Net P&L":bm[0]["total_pnl_usdt"],"Positive intervals":f"{bm[0]['positive_intervals']}/{bm[0]['intervals']}","Daily Sharpe":bm[0]["sharpe_daily"],"Max drawdown (%)":bm[0]["max_drawdown_pct"],"Avg. capital use (%)":bm[0]["avg_capital_use_pct"]},{"Method":"Equal-weight","Net P&L":bm[1]["total_pnl_usdt"],"Positive intervals":f"{bm[1]['positive_intervals']}/{bm[1]['intervals']}","Daily Sharpe":bm[1]["sharpe_daily"],"Max drawdown (%)":bm[1]["max_drawdown_pct"],"Avg. capital use (%)":bm[1]["avg_capital_use_pct"]}]),hide_index=True,width="stretch",alt="Inventory-aware greedy and equal-weight results")
  daily=[]
  for method in bm:
   for row in method["daily"]: daily.append({"Date":row["date"],"Method":method["method"],"Daily P&L":row["pnl"]})
  st.plotly_chart(px.bar(pd.DataFrame(daily),x="Date",y="Daily P&L",color="Method",barmode="group"),width="stretch",alt="Daily P&L for inventory-aware benchmark strategies")
  st.caption("Seven independent daily windows; 10,000 USDT, 0.1 BTC, and 1 ETH initially on each venue; no transfers; venue-specific taker fees; 0.05% buffer per leg; 5% volume cap; $5 minimum notional. P&L uses the MILP terminal inventory valuation convention.")
 else: st.warning("Benchmark results are missing. Run benchmark_backtest.py to generate them.")
 st.subheader("Opportunity-screen illustration (not a portfolio backtest)")
 capital=st.number_input("Benchmark capital per interval ($)",100.,1000000.,10000.,1000.)
 timeline=d.loc[d.ts.dt.minute.isin([0,30])&(d.ts.dt.second==0),"ts"].drop_duplicates().sort_values().tolist()
 curves={"Greedy":([],[]),"Equal-weight":([],[])}
 for stamp in timeline:
  g=good.loc[good["UTC time"]==stamp] if len(good) else pd.DataFrame()
  if g.empty:
   gp=ep=gu=eu=0.0
  else:
   top=g.sort_values("Net edge (%)",ascending=False).iloc[0]
   gu=min(capital,float(top["Notional"]))/capital
   gp=min(capital,float(top["Notional"]))*float(top["Net edge (%)"])/100
   alloc=np.minimum(g["Notional"].to_numpy(),capital/len(g))
   eu=float(alloc.sum()/capital)
   ep=float(np.sum(alloc*g["Net edge (%)"].to_numpy()/100))
  curves["Greedy"][0].append(gp);curves["Greedy"][1].append(gu)
  curves["Equal-weight"][0].append(ep);curves["Equal-weight"][1].append(eu)
 summary=[]
 for name,(profits,uses) in curves.items():
  arr=np.asarray(profits,dtype=float);ret=arr/capital;equity=capital+np.cumsum(arr);path=np.r_[capital,equity]
  peak=np.maximum.accumulate(path);dd=(path/peak)-1
  sd=float(np.std(ret,ddof=1)) if len(ret)>1 else 0
  sharpe=float(np.mean(ret)/sd*np.sqrt(len(ret))) if sd>0 else 0
  summary.append({"Method":name,"Screen P&L":float(arr.sum()),"Positive intervals":f"{int((arr>0).sum())}/{len(arr)}","Sample Sharpe":sharpe,"Max drawdown":abs(float(dd.min()))*100,"Avg. capital use":float(np.mean(uses))*100})
 a,b=st.columns([1.25,1])
 with a:
  st.dataframe(pd.DataFrame(summary),hide_index=True,width="stretch",alt="Greedy and equal-weight screening benchmark metrics")
 with b:
  curves_df=pd.DataFrame({"UTC time":timeline,"Greedy P&L":np.cumsum(curves["Greedy"][0]),"Equal-weight P&L":np.cumsum(curves["Equal-weight"][0])})
  fig=px.line(curves_df,x="UTC time",y=["Greedy P&L","Equal-weight P&L"],labels={"value":"Cumulative screen P&L","variable":"Method"})
  st.plotly_chart(fig,width="stretch",alt="Cumulative P&L for simplified screen benchmarks")
 st.caption("This separate opportunity screen assumes pre-positioned inventory and resets a budget each interval. Its displayed Sharpe, drawdown, and screen P&L are illustrative only; use the inventory-aware benchmark above for portfolio metrics.")
 with st.expander("Definitions / caveats"):st.write("Net edge subtracts two fee legs and two execution-buffer legs. Uses tradable flags and candle-volume caps. Transfer costs are excluded; the MILP models lags. Candle timestamps can create apparent non-simultaneous spreads.")
elif page=="MILP optimizer":
 table=[]
 for z in runs:
  ds=z["per_day"];s=z["scenario"];table.append({"Scenario":SC.get(s["name"],s["name"]),"P&L":z["total_profit_usdt"],"Trades":sum(q["n_buy"]+q["n_sell"] for q in ds),"Transfers":sum(q["n_transfers"] for q in ds),"Optimal":f"{sum(q['status_code']==0 for q in ds)}/{len(ds)}","Gap":max([q.get("mip_gap") or 0 for q in ds],default=0),"Replay":"PASS" if z["all_replay_ok"] else "REVIEW","Type":"Baseline" if s["mode"] in ("taker","maker") else "Hypothetical"})
 st.dataframe(pd.DataFrame(table),hide_index=True,width="stretch",alt="Solver metrics and replay evidence")
 for z in runs:
  if not z["all_replay_ok"]:st.warning(f"{SC.get(z['scenario']['name'],z['scenario']['name'])}: packaged result fails replay on "+", ".join(q["day"] for q in z["per_day"] if not q["replay_ok"])+f". Its{cash(z['total_profit_usdt'])} P&L is unverified.")
 st.info("PDF pages 22–30 contain older positive-return claims that conflict with the final audited solver package. results_v2.json is treated as authoritative.")
 st.subheader("Run one UTC day");a,b,c=st.columns([1,1.4,1]);day=a.selectbox("Date",days,index=days.index(last) if last in days else 0);scenario=b.selectbox("Scenario",["base_taker_buf","base_taker_nobuf","maker_both_legs","hyp_fee0.05_buf0.01"],format_func=lambda z:SC[z]);limit=c.number_input("Time limit (seconds)",1,120,15)
 if st.button("Run solver + replay audit",type="primary"):
  try:
   with st.status("Solving…",expanded=True) as status:
    out,log=run(day,scenario,int(limit))
    if out is None:status.update(label="Solver failed",state="error");st.error(log)
    else:status.update(label="Solver and replay complete",state="complete");st.session_state["latest"]=out;st.session_state["log"]=log
  except Exception as ex:st.error(f"Solver error: {ex}")
 latest=st.session_state.get("latest")
 if latest and latest.get("runs"):
  z=latest["runs"][0];q=z["per_day"][0];a,b,c,e=st.columns(4);a.metric("One-day P&L",cash(z["total_profit_usdt"]));b.metric("Buys / sells",f"{q['n_buy']} / {q['n_sell']}");c.metric("Transfers",str(q["n_transfers"]));e.metric("Replay","PASS" if q["replay_ok"] else "REVIEW",f"gap {q.get('mip_gap') or 0:.4f}")
  if q.get("trade_sample"):st.dataframe(pd.DataFrame(q["trade_sample"]),hide_index=True,width="stretch",alt="Selected trades")
  with st.expander("Solver log"):st.code(st.session_state.get("log",""))
else:
 t1,t2,t3=st.tabs(["Data quality","Model","Evidence & limits"])
 with t1:
  a,b,c,e=st.columns(4);a.metric("Rows",f"{len(df):,}");b.metric("Pairs",str(df.pair.nunique()));c.metric("Exchanges",str(df.exchange.nunique()));e.metric("Minutes",f"{df.ts.nunique():,}")
  q=[{"Exchange":LABEL[x],"Rows":len(g),"Filled":int(g.is_filled.sum()),"Stale":int(g.is_stale.sum()),"Outliers":int(g.is_outlier.sum()),"Tradable":int(g.tradable.sum()),"Quote":", ".join(sorted(g.quote_ccy.unique()))} for x,g in d.groupby("exchange")]
  st.dataframe(pd.DataFrame(q),hide_index=True,width="stretch",alt="Quality flags by exchange");st.caption("Coinbase USD prices are converted to USDT-equivalent; the currencies are not identical.")
  st.download_button("Download filtered observations",d.to_csv(index=False).encode(),file_name="market-observations.csv",mime="text/csv")
 with t2:
  st.markdown("### Objective");st.latex(r"\max\;\text{terminal USDT-equivalent inventory value} - \text{starting capital}")
  st.write("Buy/sell quantities and binaries; USDT/BTC/ETH inventory; 5% volume cap; $5 minimum notional; mutually exclusive buy/sell; per-step market neutrality; fixed withdrawal fees and transfer lags. Each day restarts with configured inventory.")
  fees=pd.read_csv(D/"params_fees.csv");fees=fees[fees.fee_type.isin(["taker_fee_pct","maker_fee_pct"])][["exchange","fee_type","fee_value","unit","source_type"]];st.dataframe(fees,hide_index=True,width="stretch",alt="Fees and provenance")
 with t3:
  st.markdown("Inputs: final_dataset market master, transfer routes, initial inventory. Evidence: results_v2.json. Formulation: MODEL.md and DECISIONS.md.")
  st.warning("Seven-day sample; candle closes are not firm simultaneous order-book quotes; depth is unavailable; USD/USDT conversion and timestamp mismatch affect spreads; transfer times are assumptions. No live profitability is established.")
  st.markdown("PDF pages 22–30 report positive returns that conflict with the final audited package; this UI uses results_v2.json.")
  with st.expander("Solver provenance"):st.json({k:ev.get(k) for k in ["grid","days","exchanges","scipy_version","assumed_parameters"]})
st.divider();st.caption("ASTER RESEARCH TERMINAL · Historical academic analysis · No API keys or exchange calls")


