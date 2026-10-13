# ASTER — Multi-Exchange Arbitrage Research UI

## Start locally

1. Install Python 3.10 or newer.
2. From this folder, run `python -m pip install -r requirements.txt`.
3. Double-click **Start Dashboard.bat** (or run `python -m streamlit run app.py`).
4. Open http://127.0.0.1:8501.

The dashboard reads only the bundled historical data. It makes no exchange API calls and requires no API keys. The MILP Optimizer page includes packaged scenario results and a one-day solver action. Opportunity Lab contains both an inventory-aware strategy comparison and a separate spread-screen illustration. Results and assumptions can be downloaded from the UI.

## Reproducible research pipeline

Run `python run_all.py` to validate the dataset, solve all 30-minute/7-day MILP scenarios, run greedy and equal-weight inventory-aware benchmarks, then regenerate figures and reports. The full MILP suite may take several minutes because some hypothetical scenarios hit the 120-second per-window limit.

`results_v2.json` is the packaged solver evidence. The baseline taker-fee, no-buffer, and maker scenarios produce zero trades and zero P&L in this sample. The hypothetical 0.05% fee scenario is not an exchange fee schedule. The hypothetical 0.05% fee scenario (negative inventory on 2026-10-05) and the hypothetical zero-fee scenario (solver/replay mismatch on 2026-10-03 and 2026-10-08) fail replay and must not be presented as verified. The dashboard labels these results accordingly.

The actual-fee benchmark resets daily, starts with 10,000 USDT, 0.1 BTC and 1 ETH per venue, uses a 5% candle-volume cap, $5 minimum order notional, venue-specific taker fees, and a 0.05% buffer on each leg. It has no transfers. It compares inventory-constrained greedy and equal-weight rules against the MILP's terminal inventory valuation convention. These are historical academic results, not executable quotes or evidence of live profitability.

## Project map

- `app.py` — locally hosted interactive Streamlit dashboard.
- `milp_solver_v2.py` — inventory-aware MILP and independent solution replay.
- `benchmark_backtest.py` — inventory-aware greedy/equal-weight benchmarks.
- `final_dataset/milp_master.csv` — cleaned 1-minute market master dataset.
- `results_v2.json`, `benchmark_results.json` — saved solver and strategy results.
- `MODEL.md`, `DECISIONS.md`, `REPORT.md` — model, design decisions and research findings.
