# Multi-Exchange Cryptocurrency Arbitrage Research

An interactive Streamlit dashboard for a historical, inventory-aware arbitrage optimization study. It presents exchange coverage, fee-aware opportunity screens, mixed-integer optimization scenarios, replay validation, benchmark comparisons, and the assumptions behind each result.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Research interpretation

This is an academic backtest over a limited historical sample, not a live trading system. Candle-close data are not simultaneous executable quotes, market depth is unavailable, transfers and fee assumptions have limitations, and the measured results do not prove future profitability. The dashboard distinguishes audited baseline outputs from hypothetical scenarios and failed replay checks.

## Project files

- `app.py` — interactive dashboard.
- `milp_solver_v2.py` — inventory-aware MILP scenario solver and replay.
- `benchmark_backtest.py` — inventory-aware strategy benchmarks.
- `final_dataset/` — cleaned market data, fee assumptions, transfer routes, and data dictionary.
- `results_v2.json`, `benchmark_results.json` — saved research outputs used by the dashboard.
- `MODEL.md`, `DECISIONS.md`, `REPORT.md` — model formulation, decisions, and research report.

## Deploy on Streamlit Community Cloud

Create a Community Cloud app from this repository, use branch `main`, and set the app file path to `app.py`. Dependencies are declared in `requirements.txt`.
