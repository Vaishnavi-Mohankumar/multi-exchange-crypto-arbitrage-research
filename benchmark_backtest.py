#!/usr/bin/env python3
"""Inventory-aware greedy and equal-weight benchmarks for ASTER's 30-minute sample."""
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
EXCHANGES=['binance','coinbase','kucoin','bitfinex','bybit','htx','cryptocom']
PAIRS=['BTC/USDT','ETH/USDT']; ASSET={'BTC/USDT':'BTC','ETH/USDT':'ETH'}
INIT={'USDT':10000.0,'BTC':0.1,'ETH':1.0}; BUFFER=0.05/100; CAP=0.05; MIN_NOTIONAL=5.0

def candidates(rows):
    out=[]
    for pair, g in rows.groupby('pair'):
        asset=ASSET[pair]; m=g.set_index('exchange')
        for buy in EXCHANGES:
            if buy not in m.index: continue
            b=m.loc[buy]
            if not bool(b.tradable) or b.close_usdt_equiv<=0: continue
            for sell in EXCHANGES:
                if sell==buy or sell not in m.index: continue
                s=m.loc[sell]
                if not bool(s.tradable): continue
                pb,ps=float(b.close_usdt_equiv),float(s.close_usdt_equiv)
                cb=pb*(1+float(b.taker_fee_pct)/100+BUFFER)
                proceeds=ps*(1-float(s.taker_fee_pct)/100-BUFFER)
                edge=proceeds-cb
                qtycap=min(float(b.volume),float(s.volume))*CAP
                if edge>0 and min(qtycap*pb,qtycap*ps)>=MIN_NOTIONAL:
                    out.append(dict(pair=pair,asset=asset,buy=buy,sell=sell,edge=edge,buy_cost=cb,
                                    sell_proceeds=proceeds,cap=qtycap,buy_price=pb,sell_price=ps))
    return sorted(out,key=lambda z:z['edge'],reverse=True)

def execute(c, inv, budget=float('inf')):
    b,s,a=c['buy'],c['sell'],c['asset']
    q=min(c['cap'],inv[b]['USDT']/c['buy_cost'],inv[s][a],budget/c['buy_cost'])
    if q*c['buy_price']<MIN_NOTIONAL or q*c['sell_price']<MIN_NOTIONAL: return 0.0,0.0
    inv[b]['USDT']-=q*c['buy_cost']; inv[b][a]+=q
    inv[s][a]-=q; inv[s]['USDT']+=q*c['sell_proceeds']
    return q*c['edge'],q*c['buy_cost']

def backtest(df,method):
    daily=[]
    for date,day in df.groupby(df.ts.dt.date,sort=True):
        day=day[day.ts.dt.minute.isin([0,30]) & day.ts.dt.second.eq(0)]
        if day.empty: continue
        venues=sorted(day.exchange.unique(),key=EXCHANGES.index)
        inv={e:dict(INIT) for e in venues}; initcash=len(venues)*INIT['USDT']
        init_base={a:len(venues)*INIT[a] for a in ('BTC','ETH')}
        start=initcash
        first_rows=day.sort_values('ts').groupby(['pair','exchange'],as_index=False).first()
        for pair,asset in ASSET.items():
            start+=sum(INIT[asset]*float(first_rows[(first_rows.pair==pair)&(first_rows.exchange==e)].close_usdt_equiv.iloc[0]) for e in venues)
        steps=[]
        for _,rows in day.groupby('ts',sort=True):
            cs=candidates(rows); pnl=used=0.0
            if method=='greedy':
                for c in cs:
                    pnl,used=execute(c,inv)
                    if pnl>0: break
            else:
                chosen=[]; busy=set()
                for c in cs:
                    if c['buy'] not in busy and c['sell'] not in busy:
                        chosen.append(c); busy.update((c['buy'],c['sell']))
                target=initcash/max(1,len(chosen))
                for c in chosen:
                    p,u=execute(c,inv,target);pnl+=p;used+=u
            steps.append((pnl,used/initcash))
        terminal={}
        for pair in PAIRS:
            q=day[day.pair.eq(pair)].sort_values('ts'); terminal[pair]=float(q.iloc[-1].close_usdt_equiv.mean())
        end=sum(x['USDT'] for x in inv.values())+sum(sum(x[a] for x in inv.values())*terminal[p] for p,a in ASSET.items())
        # Match the MILP's profit convention: value only changes in inventory, at terminal reference prices.
        pnl=sum(x['USDT'] for x in inv.values())-initcash+sum((sum(x[a] for x in inv.values())-init_base[a])*terminal[p] for p,a in ASSET.items())
        daily.append({'date':str(date),'start_value':start,'end_value':end,'pnl':pnl,
                      'positive_intervals':sum(p>1e-8 for p,_ in steps),'intervals':len(steps),
                      'interval_pnl':[p for p,_ in steps],'capital_use':[u for _,u in steps]})
    r=np.array([x['pnl']/max(1,x['start_value']) for x in daily]); pnl=np.array([x['pnl'] for x in daily])
    eq=np.r_[0,np.cumsum(pnl)]; initial=daily[0]['start_value'] if daily else 1; path=initial+eq
    dd=path/np.maximum.accumulate(path)-1
    sd=np.std(r,ddof=1) if len(r)>1 else 0
    return {'method':method,'total_pnl_usdt':float(pnl.sum()),'positive_intervals':int(sum(x['positive_intervals'] for x in daily)),
            'intervals':int(sum(x['intervals'] for x in daily)),
            'sharpe_daily':float(np.mean(r)/sd*np.sqrt(365)) if sd>0 else 0.0,
            'max_drawdown_pct':float(abs(dd.min())*100) if len(dd) else 0.0,
            'avg_capital_use_pct':float(np.mean([u for x in daily for u in x['capital_use']])*100) if daily else 0.0,
            'daily':daily}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--master',default='final_dataset/milp_master.csv');ap.add_argument('--out',default='benchmark_results.json');a=ap.parse_args()
    cols=['ts','pair','exchange','close_usdt_equiv','volume','tradable','taker_fee_pct']
    d=pd.read_csv(a.master,usecols=cols,parse_dates=['ts']);d['ts']=pd.to_datetime(d.ts,utc=True)
    out={'source':a.master,'grid':'30min','daily_windows_reset':True,'fees':'venue-specific taker','buffer_pct_per_leg':0.05,
         'volume_cap_pct':5.0,'min_notional_usdt':MIN_NOTIONAL,
         'methods':[backtest(d,'greedy'),backtest(d,'equal_weight')]}
    Path(a.out).write_text(json.dumps(out,indent=2),encoding='utf-8')
    for x in out['methods']:print(f"{x['method']}: ${x['total_pnl_usdt']:.2f}; Sharpe {x['sharpe_daily']:.3f}; MDD {x['max_drawdown_pct']:.3f}%")
if __name__=='__main__':main()


