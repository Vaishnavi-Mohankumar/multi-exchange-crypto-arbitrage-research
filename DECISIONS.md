# Engineering Decisions & Solver Architecture Log

## 1. milp_solver_v2.py as Single Source of Truth
- **Decision:** Use `milp_solver_v2.py` as the sole MILP solver engine, producing `results_v2.json`.
- **Rationale:** Formulates exact multi-asset inventory balances, transfer lags, fixed withdrawal fees, and per-period spatial neutrality without hardcoding.

## 2. Model Formulations & Discretization Grid
- **Decision:** Grid discretized to 30-minute intervals (48 steps per day) over 7 daily independent windows.
- **Rationale:** Aligns transfer lag steps ($L_{a,e_1,e_2} = \lceil \text{transfer\_time\_min} / 30 \rceil$) with computational tractability in HiGHS.

## 3. Removal of Latency Decay Claim & Fig 10
- **Decision:** Remove Fig 10 and unsubstantiated latency decay claims.
- **Rationale:** Execution delay cannot be trivially extrapolated without order book level-2 quote streaming.

## 4. Parameter Labeling and Assumptions
- **Decision:** Label all transfer times and missing fees as `source_type=assumption`.
- **Rationale:** Maintain complete audit integrity and prevent unbacked API attribution.
