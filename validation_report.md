# Validation & Feasibility Report: Multi-Exchange Cryptocurrency Arbitrage

## Executive Summary
This feasibility report evaluates empirical cross-exchange arbitrage profitability across 7 exchanges (`binance`, `coinbase`, `kucoin`, `bitfinex`, `bybit`, `htx`, `cryptocom`) for `BTC/USDT` and `ETH/USDT` over the 7-day UTC window (`2026-10-02T00:00Z` to `2026-10-09T00:00Z`).

---

## 1. Baseline Fee Scenarios & Net Profitability Empirical Findings

### Key Findings
1. **Base-Tier Taker & Maker Scenarios:** Base spot trading fees (0.10% to 0.60% per leg) strictly exceed the maximum empirical gross cross-exchange price spreads observed in the 7-day dataset (BTC max gross spread = **0.1884%**, ETH max gross spread = **0.2719%**).
2. **Zero Profitable Minutes Under Standard Scenarios:** Under `base_taker_buf0.05`, `base_taker_no_buffer`, `maker_both_legs`, and `maker_buy_taker_sell`, there are **EXACTLY 0 PROFITABLE MINUTES** across all ordered exchange pairs for both BTC/USDT and ETH/USDT.
3. **No Structural Coinbase Premium:** Empirical close prices converted to USDT-equivalents confirm that Coinbase does not trade at a structural premium sufficient to overcome its 0.60% base taker fee barrier.

### Baseline Feasibility Table (All Base Scenarios)

```
    pair             scenario  max_gross_spread_pct  best_net_pct  profitable_minutes  breakeven_fee_per_leg_pct
BTC/USDT   base_taker_buf0.05              0.188365     -0.226382                   0                   0.094094
BTC/USDT base_taker_no_buffer              0.188365     -0.126608                   0                   0.094094
BTC/USDT      maker_both_legs              0.188365     -0.126943                   0                   0.094094
BTC/USDT maker_buy_taker_sell              0.188365     -0.126943                   0                   0.094094
ETH/USDT   base_taker_buf0.05              0.271924     -0.132759                   0                   0.135777
ETH/USDT base_taker_no_buffer              0.271924     -0.032791                   0                   0.135777
ETH/USDT      maker_both_legs              0.271924     -0.032641                   0                   0.135777
ETH/USDT maker_buy_taker_sell              0.271924     -0.094170                   0                   0.135777
```

---

## 2. Hypothetical Sensitivity Analysis (For MILP Parameter Sweeps)

To enable sensitivity analysis in the MILP solver, hypothetical lower-fee tiers were evaluated:

### Sensitivity Table (Top Profitable Venue Pairs Under Hypothetical Tiers)

```
    pair              scenario buy_ex   sell_ex  max_gross_spread_pct  best_net_pct  profitable_minutes  breakeven_fee_per_leg_pct
BTC/USDT hypothetical_zero_fee    htx   binance              0.169601      0.169601                9793                   0.084729
BTC/USDT hypothetical_zero_fee    htx    kucoin              0.153654      0.153654                9783                   0.076768
BTC/USDT hypothetical_zero_fee    htx     bybit              0.173312      0.173312                9749                   0.086581
BTC/USDT hypothetical_zero_fee    htx  bitfinex              0.160409      0.160409                9735                   0.080140
BTC/USDT hypothetical_zero_fee    htx cryptocom              0.172336      0.172336                9673                   0.086094
BTC/USDT  hypothetical_0.01pct    htx  bitfinex              0.160409      0.140379                9071                   0.080140
BTC/USDT  hypothetical_0.01pct    htx   binance              0.169601      0.149569                8900                   0.084729
BTC/USDT  hypothetical_0.01pct    htx    kucoin              0.153654      0.133626                8827                   0.076768
BTC/USDT  hypothetical_0.01pct    htx cryptocom              0.172336      0.152304                8772                   0.086094
BTC/USDT  hypothetical_0.01pct    htx  coinbase              0.188365      0.168330                8705                   0.094094
ETH/USDT hypothetical_zero_fee    htx  bitfinex              0.271924      0.271924                6752                   0.135777
ETH/USDT hypothetical_zero_fee    htx   binance              0.141773      0.141773                6156                   0.070836
ETH/USDT hypothetical_zero_fee kucoin  bitfinex              0.233260      0.233260                6143                   0.116494
ETH/USDT hypothetical_zero_fee    htx     bybit              0.143846      0.143846                6142                   0.071871
ETH/USDT hypothetical_zero_fee    htx cryptocom              0.140529      0.140529                6128                   0.070215
ETH/USDT  hypothetical_0.01pct    htx  bitfinex              0.271924      0.251871                4105                   0.135777
ETH/USDT  hypothetical_0.01pct    htx     bybit              0.143846      0.123819                3616                   0.071871
ETH/USDT  hypothetical_0.01pct    htx  coinbase              0.163194      0.143164                3611                   0.081531
ETH/USDT  hypothetical_0.01pct    htx   binance              0.141773      0.121746                3515                   0.070836
ETH/USDT  hypothetical_0.01pct    htx cryptocom              0.140529      0.120503                3411                   0.070215
```

---

## 3. Solver Recommendations for MILP Optimisation
- **Fee Sensitivity Modeling:** Solvers attempting to trade under base-tier fees will correctly output 0 trades. MILP parameter sweeps must evaluate VIP fee schedules or fee thresholds below the break-even level (**< 0.094% per leg for BTC**, **< 0.136% per leg for ETH**).
- **Grid Optimization:** Use `prices_resampled_5m.csv` or `prices_1day_slice.csv` for fast MILP matrix solving before scaling to the full 1-minute grid.

---

## 4. Project Limitations
1. **Timing Artifacts:** 1-minute close prices represent the last trade in each 60s window.
2. **Order Book Slippage:** Modeled as empirical spread buffer per exchange/pair from order book depth sampling.
3. **On-Chain Transfer Delays:** On-chain transfer delays (BTC 60m, ETH 3m) require MILP transfer decision variables to be modeled with lag steps $L$.
