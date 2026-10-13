# Multi-Exchange Cryptocurrency Arbitrage Optimisation using MILP
**Final Engineering & Operations Research Report**  
*Single Source of Truth:* `results_v2.json`  
*Grid Resolution:* 30min (7 Days, 48 steps/day) | *Solver Engine:* HiGHS (via SciPy 1.18.1)  
*Venues:* Binance, Coinbase, KuCoin, Bitfinex, Bybit, HTX, Crypto.com  

---

## 1. Executive Summary & Measured Findings
This project formulates and solves an inventory-aware Mixed-Integer Linear Programming (MILP) model to determine whether spatial cryptocurrency arbitrage exists across 7 major spot exchanges.

### Empirical Findings:
- **Baseline Realistic Scenarios:** Under base-tier taker fees (0.10%–0.60%) with or without execution buffer, **total net profit is exactly $0.00** across all 7 days.
- **Maker Scenario:** Under the packaged maker fee assumptions and execution buffer, net profit is **$0.00** with 0 executed trades.
- **Gross vs. Fee Screen:** Maximum raw candle-close spreads reached **0.1884%** (BTC) and **0.2719%** (ETH); the ETH peak exceeds 0.20%. These are unfiltered historical close-price extremes, not executable opportunities. The realistic-fee MILP scenarios nevertheless returned $0.00 and no trades.
- **Analytical Break-Even Thresholds:**
  - **BTC/USDT Break-Even Fee:** **< 0.0942% per leg**
  - **ETH/USDT Break-Even Fee:** **< 0.1360% per leg**
- **Hypothetical Parameter Sensitivity:**
  - When fees are hypothetically reduced to **0.05% per leg** (0.01% buffer), spatial arbitrage emerges, yielding **$36.60** in net profit across 20 buy orders, 42 sell orders, and 23 rebalancing transfers.
  - Disabling inter-exchange transfers drops net profit to **$14.80** due to localized inventory depletion.
  - The 2x-inventory scenario reports **$118.03**; replay passed, and some windows were not proven optimal.
  - At 0.02% fee / 0.01% buffer, the model reports **$1208.67**; replay passed, with 4 of 7 windows not proven optimal.
  - At zero fees and zero buffer, the solver reports **$5344.77**, but replay FAILED and 7 of 7 windows were not proven optimal; treat this as an unvalidated upper-bound sensitivity only.

---

## 2. Solver Evidence & Measured Performance Summary

The table below reports exact solver metrics extracted directly from `results_v2.json`:

| Scenario ID | Net Profit (USDT) | Buys | Sells | Transfers | Decision Vars | Constraints | Solve Time (s) | Worst Gap |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `base_taker_buf` | **$0.00** | 0 | 0 | 0 | 9,662 | 7,447 | 4.80s | 0.0000 |
| `base_taker_nobuf` | **$0.00** | 0 | 0 | 0 | 9,662 | 7,447 | 4.82s | 0.0000 |
| `maker_both_legs` | **$0.00** | 0 | 0 | 0 | 9,662 | 7,447 | 4.80s | 0.0000 |
| `hyp_fee0.05_buf0.01 *` | **$36.60** | 20 | 42 | 23 | 9,662 | 7,447 | 365.15s | 0.0864 |
| `hyp_fee0.05_buf0.01_no_transfers` | **$14.80** | 8 | 10 | 0 | 3,698 | 4,465 | 2.75s | 0.0059 |
| `hyp_fee0.05_buf0.01_inv2x` | **$118.03** | 19 | 32 | 30 | 9,662 | 7,447 | 367.39s | 0.0652 |
| `hyp_fee0.02_buf0.01` | **$1208.67** | 146 | 200 | 174 | 9,662 | 7,447 | 652.72s | 0.0677 |
| `hyp_fee0.00_buf0.00 *` | **$5344.77** | 655 | 727 | 357 | 9,662 | 7,447 | 841.07s | 1.1757 |

---

## 3. Mathematical Model Formulation (`milp_solver_v2.py`)

The mathematical model implemented in `milp_solver_v2.py` enforces real balance tracking, inter-exchange transfer dynamics, Big-M execution logic, per-period market neutrality, and mark-to-market terminal evaluation:

### 3.1 Decision Variables
- $buy_{p,e,t}, sell_{p,e,t} \ge 0$: Quantities bought and sold for pair $p$ on exchange $e$ at time step $t$.
- $ub_{p,e,t}, us_{p,e,t} \in \{0, 1\}$: Binary indicators for buy and sell order execution.
- $inv_{a,e,t} \ge 0$: Inventory balance of asset $a$ (USDT, BTC, ETH) on exchange $e$ at end of step $t$.
- $send_{a,e_1,e_2,t} \ge 0$: Quantity of asset $a$ transferred from exchange $e_1$ to $e_2$.
- $z_{a,e_1,e_2,t} \in \{0, 1\}$: Binary indicator for transfer activation incurring fixed fee $F_{a,e_1,e_2}^{\text{tx}}$.

### 3.2 Constraints
1. **Big-M Volume Cap:** $buy_{p,e,t} \le \kappa \cdot Vol_{p,e,t} \cdot ub_{p,e,t}$ and $sell_{p,e,t} \le \kappa \cdot Vol_{p,e,t} \cdot us_{p,e,t}$ with $\kappa = 0.05$.
2. **Mutual Exclusion:** $ub_{p,e,t} + us_{p,e,t} \le 1$ (no simultaneous buy and sell on the same venue).
3. **Minimum Notional:** $Pr_{p,e,t} \cdot buy_{p,e,t} \ge N^{\min} \cdot ub_{p,e,t}$ with $N^{\min} = \$5.00$.
4. **Per-Period Spatial Neutrality:** $\sum_{e} buy_{p,e,t} = \sum_{e} sell_{p,e,t} \quad \forall p, t$ (pure spatial arbitrage; no directional market speculation).
5. **Transfer Lags & Fees:** $L_{a,e_1,e_2} = \lceil \text{transfer\_time\_min} / \text{grid\_min} \rceil$ delay steps with fixed withdrawal deductions.
6. **Marked-to-Market Objective:**
   $$\max \sum_{e} inv_{\text{USDT},e,N_T} + \sum_{a \in \{\text{BTC},\text{ETH}\}} \bar{Pr}_{a,N_T} \sum_{e} (inv_{a,e,N_T} - I_{a,e,0}) - \sum_{e} I_{\text{USDT},e,0}$$

---

## 4. Methodological Limitations
1. **Candle Close Prices:** OHLCV candle closes represent the last executed transaction in a 30-minute interval, not instantaneous executable limit order book quotes.
2. **Coinbase USD vs USDT:** Coinbase pairs are quoted in USD rather than USDT. While pegged (mean deviation 0.0301%), fiat-stablecoin conversion spreads are not modeled.
3. **Execution Buffer:** The 0.05% per-leg buffer is a model assumption; no level-2 execution is simulated.
4. **Daily Independent Windows:** Optimization windows reset daily at 00:00 UTC starting from initial inventory, precluding multi-day inventory carry.

---
*Generated by `generate_reports.py` | Single Source of Truth: `results_v2.json`*
