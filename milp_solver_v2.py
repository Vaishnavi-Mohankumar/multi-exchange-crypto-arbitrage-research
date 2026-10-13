#!/usr/bin/env python3
"""
milp_solver_v2.py - inventory-aware multi-exchange arbitrage MILP (scipy / HiGHS).

What this fixes versus milp_solver.py
  * Real inventory balances per exchange and asset (USDT, BTC, ETH) -> capital limits.
  * Inter-exchange transfers with lag (ceil(transfer_time / grid)) and a fixed withdrawal fee
    (binary activation), as described in MODEL.md.
  * Buy/sell binaries with big-M volume cap, minimum notional and mutual exclusion.
  * Per-period market neutrality (buys = sells every step) so profit is spatial arbitrage, not price speculation.
  * An independent replay audit that recomputes balances from the solution.
  * Every number in the output (vars, constraints, runtime, status, gap) is measured, not typed in.

Usage
  python milp_solver_v2.py --selftest
  python milp_solver_v2.py --master final_dataset/milp_master.csv --params params.csv \
         --grid 30min --days 7 --time-limit 120

Input files
  master csv : columns ts, pair, exchange, close_usdt_equiv, volume   (1-minute candles)
  params csv : tidy format with columns exchange, parameter, value
               parameters used: taker_fee_pct, maker_fee_pct, btc/eth/usdt_withdrawal_fee_*,
               btc/eth/usdt_transfer_time_min.  'MISSING' values are filled with the median of
               the other exchanges and reported as ASSUMED in the output.

Modelling choices (state these in the report)
  * Each day is solved as an independent window starting from the initial inventory.
  * Candle closes are treated as executable prices (no order-book depth); fees + buffer are
    applied on both legs.
  * Coinbase USD prices are treated as USDT-equivalent (as in the original dataset).
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import coo_matrix

PAIRS = ["BTC/USDT", "ETH/USDT"]
ASSETS = ["USDT", "BTC", "ETH"]
DEFAULT_EXCH = ["binance", "coinbase", "kucoin", "bitfinex", "bybit", "htx", "cryptocom"]
INIT_INV = {"USDT": 10_000.0, "BTC": 0.1, "ETH": 1.0}
MIN_NOTIONAL = 5.0

SCENARIOS = [
    dict(name="base_taker_buf", mode="taker", buffer_pct=0.05),
    dict(name="base_taker_nobuf", mode="taker", buffer_pct=0.0),
    dict(name="maker_both_legs", mode="maker", buffer_pct=0.05),
    dict(name="hyp_fee0.05_buf0.01", mode="override", fee_pct=0.05, buffer_pct=0.01),
    dict(name="hyp_fee0.05_buf0.01_no_transfers", mode="override", fee_pct=0.05, buffer_pct=0.01, transfers=False),
    dict(name="hyp_fee0.05_buf0.01_inv2x", mode="override", fee_pct=0.05, buffer_pct=0.01, inv_mult=2.0),
    dict(name="hyp_fee0.02_buf0.01", mode="override", fee_pct=0.02, buffer_pct=0.01),
    dict(name="hyp_fee0.00_buf0.00", mode="override", fee_pct=0.0, buffer_pct=0.0),
]


# ----------------------------------------------------------------------------------------
# data loading
# ----------------------------------------------------------------------------------------
def load_params(path, exch):
    df = pd.read_csv(path)
    df["v"] = pd.to_numeric(df["value"], errors="coerce")
    assumed = []

    def get(param):
        s = df[df["parameter"] == param].groupby("exchange")["v"].first().reindex(exch)
        miss = s[s.isna()].index.tolist()
        if miss:
            fill = s.median()
            if not np.isfinite(fill):
                raise ValueError(f"parameter {param} missing for all exchanges")
            assumed.append(f"{param}: {miss} filled with median {fill:g}")
            s = s.fillna(fill)
        return s.values.astype(float)

    par = {
        "taker": get("taker_fee_pct") / 100.0,
        "maker": get("maker_fee_pct") / 100.0,
        # fixed withdrawal fee per exchange and asset (units of that asset)
        "F": np.column_stack([get("usdt_withdrawal_fee_usdt"),
                              get("btc_withdrawal_fee_btc"),
                              get("eth_withdrawal_fee_eth")]),
        "tmin": np.column_stack([get("usdt_transfer_time_min"),
                                 get("btc_transfer_time_min"),
                                 get("eth_transfer_time_min")]),
        "assumed": assumed,
    }
    return par


def load_grid(path, exch, grid):
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    P, V, OK = {}, {}, {}
    for p in PAIRS:
        d = df[df["pair"] == p]
        pc = d.pivot(index="ts", columns="exchange", values="close_usdt_equiv").reindex(columns=exch)
        pv = d.pivot(index="ts", columns="exchange", values="volume").reindex(columns=exch)
        pc = pc.resample(grid).last()
        pv = pv.resample(grid).sum(min_count=1)
        ok = pc.notna() & pv.notna() & (pv > 0) & (pc > 0)
        P[p] = pc.ffill().bfill().values.astype(float)
        V[p] = pv.fillna(0.0).values.astype(float)
        OK[p] = ok.values
        idx = pc.index
    return idx, P, V, OK


# ----------------------------------------------------------------------------------------
# model
# ----------------------------------------------------------------------------------------
class Vars:
    def __init__(self):
        self.n, self.lb, self.ub, self.integ, self.c = 0, [], [], [], []

    def add(self, lb, ub, integ=0, c=0.0):
        i = self.n
        self.n += 1
        self.lb.append(lb); self.ub.append(ub); self.integ.append(integ); self.c.append(c)
        return i


class Rows:
    def __init__(self):
        self.r, self.c, self.v, self.lo, self.hi, self.n = [], [], [], [], [], 0

    def add(self, terms, lo, hi):
        for col, val in terms:
            self.r.append(self.n); self.c.append(col); self.v.append(val)
        self.lo.append(lo); self.hi.append(hi)
        self.n += 1


def fee_vectors(par, sc):
    nE = len(par["taker"])
    mode = sc.get("mode", "taker")
    if mode == "taker":
        return par["taker"], par["taker"]
    if mode == "maker":
        return par["maker"], par["maker"]
    if mode == "maker_buy_taker_sell":
        return par["maker"], par["taker"]
    if mode == "override":
        f = np.full(nE, sc["fee_pct"] / 100.0)
        return f, f
    raise ValueError(mode)


def solve_window(P, V, OK, exch, par, sc, time_limit, gap, grid_min):
    nE, nP = len(exch), len(PAIRS)
    T = P[PAIRS[0]].shape[0]
    fb, fs = fee_vectors(par, sc)
    beta = sc.get("buffer_pct", 0.0) / 100.0
    kappa = sc.get("kappa", 0.05)
    transfers = sc.get("transfers", True)
    init = np.tile([INIT_INV[a] for a in ASSETS], (nE, 1)) * sc.get("inv_mult", 1.0)
    F = par["F"]
    lag = np.maximum(1, np.ceil(par["tmin"] / grid_min)).astype(int)

    tot = init.sum(axis=0)
    transfer_every = int(sc.get("transfer_every", 1))
    V_, R_ = Vars(), Rows()
    buy = np.zeros((T, nE, nP), int); sell = buy.copy(); ubv = buy.copy(); usv = buy.copy()
    inv = np.zeros((T, nE, 3), int)

    # reference price used ONLY to value the (tiny) change in base-asset inventory at the end
    # (base inventory can only shrink through withdrawal fees).  Profit = dUSDT + dBase * pref.
    pref = np.array([float(np.mean(P[p][T - 1])) for p in PAIRS])

    for t in range(T):
        for e in range(nE):
            for k, p in enumerate(PAIRS):
                price = P[p][t, e]
                cap = kappa * V[p][t, e] if OK[p][t, e] else 0.0
                cap = min(cap, 1.0001 * tot[k + 1])     # tight big-M: system base inventory only shrinks
                feas = cap * price >= MIN_NOTIONAL * 1.0000001
                hi = cap if feas else 0.0
                buy[t, e, k] = V_.add(0.0, hi)
                sell[t, e, k] = V_.add(0.0, hi)
                ubv[t, e, k] = V_.add(0.0, 1.0 if feas else 0.0, 1)
                usv[t, e, k] = V_.add(0.0, 1.0 if feas else 0.0, 1)
            for a in range(3):
                inv[t, e, a] = V_.add(0.0, np.inf, 0, 0.0)
    # profit variable: objective is profit itself, so the MIP gap is relative to profit
    # (not to the ~170k total portfolio value)
    prof = V_.add(-np.inf, np.inf, 0, -1.0)
    # constant offset K so that the relative MIP gap acts like an ABSOLUTE tolerance of ~abs_tol USDT
    # (scipy.milp has no absolute-gap option): tolerance ~ gap * (profit + K)
    K = float(sc.get("abs_tol_usdt", 1.0)) / max(gap, 1e-9)
    kconst = V_.add(K, K, 0, -1.0)

    sendv, wv = {}, {}
    if transfers:
        for t in range(T):
            for e1 in range(nE):
                for e2 in range(nE):
                    if e1 == e2:
                        continue
                    for a in range(3):
                        if t % transfer_every != 0:
                            continue            # transfer decisions only on the allowed steps
                        if t + lag[e1, a] > T - 1:
                            continue            # would arrive after the window -> never useful
                        sendv[(t, e1, e2, a)] = V_.add(0.0, np.inf)
                        wv[(t, e1, e2, a)] = V_.add(0.0, 1.0, 1)

    # big-M for transfers: everything that can exist in the system
    # with per-period neutrality total BTC/ETH can only shrink (withdrawal fees); USDT changes only by profit
    Mx = np.array([1.5 * tot[0], 1.0001 * tot[1], 1.0001 * tot[2]])

    # trade logic
    for t in range(T):
        for e in range(nE):
            for k, p in enumerate(PAIRS):
                price = P[p][t, e]
                cap = kappa * V[p][t, e] if OK[p][t, e] else 0.0
                cap = min(cap, 1.0001 * tot[k + 1])
                if cap * price < MIN_NOTIONAL * 1.0000001:
                    continue
                b, s, u1, u2 = buy[t, e, k], sell[t, e, k], ubv[t, e, k], usv[t, e, k]
                R_.add([(b, 1.0), (u1, -cap)], -np.inf, 0.0)
                R_.add([(s, 1.0), (u2, -cap)], -np.inf, 0.0)
                R_.add([(b, price), (u1, -MIN_NOTIONAL)], 0.0, np.inf)
                R_.add([(s, price), (u2, -MIN_NOTIONAL)], 0.0, np.inf)
                R_.add([(u1, 1.0), (u2, 1.0)], -np.inf, 1.0)

    # transfer activation
    for key, si in sendv.items():
        R_.add([(si, 1.0), (wv[key], -Mx[key[3]])], -np.inf, 0.0)

    # inventory balances
    for t in range(T):
        for e in range(nE):
            for a in range(3):
                terms = [(inv[t, e, a], 1.0)]
                rhs = 0.0
                if t > 0:
                    terms.append((inv[t - 1, e, a], -1.0))
                else:
                    rhs = init[e, a]
                if a == 0:
                    for k, p in enumerate(PAIRS):
                        price = P[p][t, e]
                        terms.append((buy[t, e, k], price * (1.0 + fb[e] + beta)))
                        terms.append((sell[t, e, k], -price * (1.0 - fs[e] - beta)))
                else:
                    k = a - 1
                    terms.append((buy[t, e, k], -1.0))
                    terms.append((sell[t, e, k], 1.0))
                if transfers:
                    for e2 in range(nE):
                        if e2 != e and (t, e, e2, a) in sendv:
                            terms.append((sendv[(t, e, e2, a)], 1.0))
                            terms.append((wv[(t, e, e2, a)], F[e, a]))
                    for e1 in range(nE):
                        if e1 == e:
                            continue
                        key = (t - lag[e1, a], e1, e, a)
                        if key[0] >= 0 and key in sendv:
                            terms.append((sendv[key], -1.0))
                R_.add(terms, rhs, rhs)

    # PER-PERIOD market neutrality: in every step, total base bought across exchanges equals total
    # base sold.  Without this, a perfect-foresight optimiser with inventory earns money by
    # speculating on price moves (buy low / sell high over the day) instead of arbitraging.
    for t in range(T):
        for k in range(nP):
            R_.add([(buy[t, e, k], 1.0) for e in range(nE)] + [(sell[t, e, k], -1.0) for e in range(nE)], 0.0, 0.0)

    # profit = (final USDT + pref * final base) - (initial USDT + pref * initial base)
    init_val = init[:, 0].sum() + float(init[:, 1:].sum(axis=0) @ pref)
    R_.add([(prof, 1.0)] + [(inv[T - 1, e, 0], -1.0) for e in range(nE)]
           + [(inv[T - 1, e, k + 1], -pref[k]) for e in range(nE) for k in range(nP)], -init_val, -init_val)

    A = coo_matrix((R_.v, (R_.r, R_.c)), shape=(R_.n, V_.n)).tocsr()
    t0 = time.perf_counter()
    res = milp(c=np.array(V_.c), integrality=np.array(V_.integ),
               bounds=Bounds(np.array(V_.lb), np.array(V_.ub)),
               constraints=LinearConstraint(A, np.array(R_.lo), np.array(R_.hi)),
               options={"time_limit": time_limit, "mip_rel_gap": gap, "disp": False})
    runtime = time.perf_counter() - t0

    out = dict(n_vars=V_.n, n_constraints=R_.n, n_binaries=int(sum(V_.integ)),
               status_code=int(res.status), status=str(res.message), runtime_sec=round(runtime, 3),
               mip_gap=(float(res.mip_gap) if getattr(res, "mip_gap", None) is not None else None))
    if res.x is None:
        out.update(solver_objective=0.0, replay_objective=0.0, n_buy=0, n_sell=0, n_transfers=0,
                   replay_ok=False, note="no feasible solution returned")
        return out, []

    x = res.x
    Buy = x[buy]; Sell = x[sell]
    Buy = np.where(x[ubv] > 0.5, Buy, 0.0)       # clean integrality dust
    Sell = np.where(x[usv] > 0.5, Sell, 0.0)
    Buy[Buy < 1e-9] = 0.0; Sell[Sell < 1e-9] = 0.0
    S = np.zeros((T, nE, nE, 3))
    for key, si in sendv.items():
        if x[wv[key]] > 0.5 and x[si] > 1e-9:
            S[key] = x[si]

    # independent replay of the balances
    inv_r = init.copy()
    pending = np.zeros((T + int(lag.max()) + 2, nE, 3))
    min_inv = np.inf
    for t in range(T):
        inv_r = inv_r + pending[t]
        for e in range(nE):
            for k, p in enumerate(PAIRS):
                price = P[p][t, e]
                inv_r[e, 0] += -price * (1 + fb[e] + beta) * Buy[t, e, k] + price * (1 - fs[e] - beta) * Sell[t, e, k]
                inv_r[e, k + 1] += Buy[t, e, k] - Sell[t, e, k]
        for e1 in range(nE):
            for e2 in range(nE):
                for a in range(3):
                    s = S[t, e1, e2, a]
                    if s > 0:
                        inv_r[e1, a] -= s + F[e1, a]
                        pending[t + lag[e1, a], e2, a] += s
        min_inv = min(min_inv, float(inv_r.min()))
    d_base = inv_r[:, 1:].sum(axis=0) - init[:, 1:].sum(axis=0)          # change in BTC / ETH holdings
    replay_obj = float(inv_r[:, 0].sum() - init[:, 0].sum() + float(d_base @ pref))
    neutral_gap = float(np.max(np.abs(Buy.sum(axis=1) - Sell.sum(axis=1))))
    neutral_ok = bool(neutral_gap < 1e-5)
    solver_obj = float(-res.fun - K)
    viol_rows = np.maximum(np.maximum(np.array(R_.lo) - (A @ x), (A @ x) - np.array(R_.hi)), 0.0)
    max_viol = float(np.max(viol_rows)) if len(viol_rows) else 0.0
    ints = np.array(V_.integ) == 1
    max_int_dev = float(np.max(np.abs(x[ints] - np.round(x[ints])))) if ints.any() else 0.0

    trades = []
    for t, e, k in zip(*np.nonzero(Buy > 0)):
        trades.append(dict(t=int(t), side="buy", exchange=exch[e], pair=PAIRS[k], qty=float(Buy[t, e, k]), price=float(P[PAIRS[k]][t, e])))
    for t, e, k in zip(*np.nonzero(Sell > 0)):
        trades.append(dict(t=int(t), side="sell", exchange=exch[e], pair=PAIRS[k], qty=float(Sell[t, e, k]), price=float(P[PAIRS[k]][t, e])))
    for t, e1, e2, a in zip(*np.nonzero(S > 0)):
        trades.append(dict(t=int(t), side="transfer", asset=ASSETS[a], frm=exch[e1], to=exch[e2], qty=float(S[t, e1, e2, a])))

    replay_ok = bool(min_inv > -1e-4 and neutral_ok and abs(replay_obj - solver_obj) < max(0.05, 1e-3 * abs(solver_obj)))
    note = None
    if res.status != 0 and replay_obj < 0:
        # time limit hit and the incumbent is worse than doing nothing -> do-nothing (0) is a valid lower bound
        note = "time limit: incumbent worse than do-nothing; reported 0 as lower bound"
        replay_obj, replay_ok, trades = 0.0, True, []
        Buy[:] = 0.0; Sell[:] = 0.0; S[:] = 0.0
    out.update(note=note, solver_objective=round(solver_obj, 4), replay_objective=round(replay_obj, 4),
               n_buy=int((Buy > 0).sum()), n_sell=int((Sell > 0).sum()), n_transfers=int((S > 0).sum()),
               max_constraint_violation=max_viol, max_integrality_deviation=max_int_dev,
               min_inventory_after_replay=round(min_inv, 8), per_period_neutral_ok=neutral_ok,
               base_change_btc_eth=[round(float(v), 8) for v in d_base],
               replay_ok=replay_ok)
    return out, trades


# ----------------------------------------------------------------------------------------
# driver
# ----------------------------------------------------------------------------------------
def run(master, params, grid, days, time_limit, gap, names, out_path, exch, transfer_every=2):
    grid_min = pd.Timedelta(grid).total_seconds() / 60.0
    par = load_params(params, exch)
    idx, P, V, OK = load_grid(master, exch, grid)
    steps = int(round(24 * 60 / grid_min))
    n_days = min(days, len(idx) // steps) if days else len(idx) // steps
    print(f"grid={grid} steps/day={steps} days={n_days} exchanges={len(exch)}")
    for note in par["assumed"]:
        print("ASSUMED:", note)

    results = []
    for sc in SCENARIOS:
        if names and sc["name"] not in names:
            continue
        sc = {**sc, "transfer_every": transfer_every}
        per_day, tot_replay, tot_solver = [], 0.0, 0.0
        for d in range(n_days):
            sl = slice(d * steps, (d + 1) * steps)
            Pd = {p: P[p][sl] for p in PAIRS}; Vd = {p: V[p][sl] for p in PAIRS}; Od = {p: OK[p][sl] for p in PAIRS}
            r, trades = solve_window(Pd, Vd, Od, exch, par, sc, time_limit, gap, grid_min)
            r["day"] = str(idx[d * steps].date())
            r["trade_sample"] = trades[:60]
            per_day.append(r)
            tot_replay += r["replay_objective"]; tot_solver += r["solver_objective"]
            print(f"  {sc['name']:<36} {r['day']}  profit={r['replay_objective']:>10.2f}  "
                  f"buys={r['n_buy']:>3} sells={r['n_sell']:>3} xfers={r['n_transfers']:>3}  "
                  f"vars={r['n_vars']:,} cons={r['n_constraints']:,}  {r['runtime_sec']}s  replay_ok={r['replay_ok']}")
        results.append(dict(scenario=sc, total_profit_usdt=round(tot_replay, 4), total_solver_objective=round(tot_solver, 4),
                            all_replay_ok=all(r["replay_ok"] for r in per_day), per_day=per_day))
    summary = dict(grid=grid, days=n_days, exchanges=exch, assumed_parameters=par["assumed"],
                   initial_inventory_per_exchange=INIT_INV, min_notional=MIN_NOTIONAL,
                   scipy_version=__import__("scipy").__version__, runs=results)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    tab = pd.DataFrame([dict(scenario=r["scenario"]["name"], total_profit_usdt=r["total_profit_usdt"],
                             buys=sum(x["n_buy"] for x in r["per_day"]), sells=sum(x["n_sell"] for x in r["per_day"]),
                             transfers=sum(x["n_transfers"] for x in r["per_day"]),
                             windows_not_proven_optimal=sum(1 for x in r["per_day"] if x["status_code"] != 0),
                             worst_gap=max([x["mip_gap"] or 0 for x in r["per_day"]]),
                             max_runtime_sec=max(x["runtime_sec"] for x in r["per_day"]),
                             all_replay_ok=r["all_replay_ok"]) for r in results])
    tab.to_csv(out_path.replace(".json", "_summary.csv"), index=False)
    print("\n" + tab.to_string(index=False))
    print(f"\nSaved {out_path} and {out_path.replace('.json', '_summary.csv')}")
    return summary


# ----------------------------------------------------------------------------------------
# self test on synthetic data (checks the model logic without your dataset)
# ----------------------------------------------------------------------------------------
def selftest(workdir):
    os.makedirs(workdir, exist_ok=True)
    rng = np.random.default_rng(7)
    exch = DEFAULT_EXCH
    ts = pd.date_range("2026-10-02", periods=2 * 1440, freq="1min", tz="UTC")
    rows = []
    for p, p0 in zip(PAIRS, [100_000.0, 4_000.0]):
        base = p0 * np.exp(np.cumsum(rng.normal(0, 2e-4, len(ts))))
        for i, e in enumerate(exch):
            offset = {"htx": -0.0006}.get(e, 0.0)               # HTX persistently 6 bp cheaper
            noise = rng.normal(0, 1.5e-4, len(ts))
            px = base * (1 + offset + noise)
            vol = rng.uniform(5, 30, len(ts)) * (1 if p.startswith("BTC") else 20)
            rows.append(pd.DataFrame(dict(ts=ts.strftime("%Y-%m-%dT%H:%M:%SZ"), pair=p, exchange=e,
                                          close_usdt_equiv=px, volume=vol)))
    pd.concat(rows).to_csv(f"{workdir}/master.csv", index=False)
    fees = dict(binance=.1, coinbase=.6, kucoin=.1, bitfinex=.2, bybit=.1, htx=.2, cryptocom=.5)
    pr = []
    for e in exch:
        pr += [(e, "taker_fee_pct", fees[e]), (e, "maker_fee_pct", fees[e] / 2),
               (e, "btc_withdrawal_fee_btc", "MISSING" if e == "coinbase" else 0.0005),
               (e, "eth_withdrawal_fee_eth", 0.0016), (e, "usdt_withdrawal_fee_usdt", 1.0),
               (e, "btc_transfer_time_min", 60), (e, "eth_transfer_time_min", 3), (e, "usdt_transfer_time_min", 1)]
    pd.DataFrame(pr, columns=["exchange", "parameter", "value"]).to_csv(f"{workdir}/params.csv", index=False)
    return f"{workdir}/master.csv", f"{workdir}/params.csv"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="final_dataset/milp_master.csv")
    ap.add_argument("--params", default="params.csv")
    ap.add_argument("--grid", default="30min")
    ap.add_argument("--transfer-every", type=int, default=2, help="allow transfer decisions every k-th step")
    ap.add_argument("--days", type=int, default=0, help="0 = all full days")
    ap.add_argument("--time-limit", type=float, default=120.0)
    ap.add_argument("--gap", type=float, default=0.001)
    ap.add_argument("--scenarios", nargs="*", default=None)
    ap.add_argument("--out", default="results_v2.json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        m, p = selftest("selftest_data")
        run(m, p, a.grid, 1, a.time_limit, a.gap, a.scenarios, "selftest_data/results_v2.json", DEFAULT_EXCH, a.transfer_every)
    else:
        run(a.master, a.params, a.grid, a.days, a.time_limit, a.gap, a.scenarios, a.out, DEFAULT_EXCH, a.transfer_every)
