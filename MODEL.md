# MILP MATHEMATICAL FORMULATION (MODEL.MD)

**Project:** Multi-Exchange Cryptocurrency Arbitrage Optimisation using MILP  
**Implementation Reference:** `milp_solver_v2.py`  
**Objective:** Maximise spatial arbitrage USDT capital across exchanges over 7 daily independent 30-minute discretization windows, enforcing per-period market neutrality, real asset balances, inter-exchange transfer lags and fixed network fees, Big-M volume caps, and minimum notionals.

---

## 1. Sets & Indices

- $t \in T = \{1, 2, \dots, N_T\}$: Discrete time steps ($N_T = 48$ steps per day at 30-min grid resolution).
- $e \in E = \{\text{binance}, \text{coinbase}, \text{kucoin}, \text{bitfinex}, \text{bybit}, \text{htx}, \text{cryptocom}\}$: Spot exchange venues ($|E| = 7$).
- $p \in P = \{\text{BTC/USDT}, \text{ETH/USDT}\}$: Base-quote trading pairs ($|P| = 2$).
- $a \in A = \{\text{USDT}, \text{BTC}, \text{ETH}\}$: Asset types ($|A| = 3$).
- $(a, e_1, e_2) \in R$: Feasible directed transfer routes for asset $a$ from exchange $e_1$ to $e_2$ ($e_1 \ne e_2$).

---

## 2. Model Parameters

- $Pr_{p,e,t} > 0$: USDT-equivalent close price of pair $p$ on exchange $e$ at time $t$ (`close_usdt_equiv`).
- $Vol_{p,e,t} \ge 0$: Trading volume of pair $p$ on exchange $e$ at time $t$.
- $\kappa \in (0, 1]$: Volume liquidity cap factor (default $\kappa = 0.05$ or 5%).
- $\phi_e^{\text{buy}}, \phi_e^{\text{sell}} \ge 0$: Taker or Maker spot trading fee percentages (in decimal).
- $\beta \ge 0$: Execution spread buffer percentage (default $\beta = 0.05\%$ or $0.0005$).
- $F_{a,e_1,e_2}^{\text{tx}} \ge 0$: Fixed network withdrawal fee in units of asset $a$.
- $L_{a,e_1,e_2} \in \mathbb{Z}^+$: Discrete transfer delay steps ($L_{a,e_1,e_2} = \lceil \text{transfer\_time\_min} / \text{grid\_min} \rceil$).
- $N^{\min} = 5.0$: Minimum order notional threshold in USDT.
- $I_{a,e,0} \ge 0$: Initial starting inventory balance ($10,000$ USDT, $0.1$ BTC, $1.0$ ETH per exchange).

---

## 3. Decision Variables

- $buy_{p,e,t} \ge 0$: Quantity of pair $p$ bought on exchange $e$ at step $t$.
- $sell_{p,e,t} \ge 0$: Quantity of pair $p$ sold on exchange $e$ at step $t$.
- $ub_{p,e,t} \in \{0, 1\}$: Binary indicator for buy order execution.
- $us_{p,e,t} \in \{0, 1\}$: Binary indicator for sell order execution.
- $inv_{a,e,t} \ge 0$: Non-negative inventory balance of asset $a$ on exchange $e$ at end of step $t$.
- $send_{a,e_1,e_2,t} \ge 0$: Quantity of asset $a$ transferred from $e_1$ to $e_2$ initiated at step $t$.
- $z_{a,e_1,e_2,t} \in \{0, 1\}$: Binary indicator for transfer activation.

---

## 4. Constraint Equations

### 4.1 Big-M Volume Cap & Execution Constraints
$$buy_{p,e,t} \le \kappa \cdot Vol_{p,e,t} \cdot ub_{p,e,t}, \quad \forall p, e, t$$
$$sell_{p,e,t} \le \kappa \cdot Vol_{p,e,t} \cdot us_{p,e,t}, \quad \forall p, e, t$$

### 4.2 Mutual Exclusion
$$ub_{p,e,t} + us_{p,e,t} \le 1, \quad \forall p, e, t$$

### 4.3 Minimum Order Notional
$$Pr_{p,e,t} \cdot buy_{p,e,t} \ge N^{\min} \cdot ub_{p,e,t}, \quad \forall p, e, t$$
$$Pr_{p,e,t} \cdot sell_{p,e,t} \ge N^{\min} \cdot us_{p,e,t}, \quad \forall p, e, t$$

### 4.4 Per-Period Market Neutrality (Pure Spatial Arbitrage)
To prevent directional price speculation, total units bought across all venues must equal total units sold across all venues at every step $t$:
$$\sum_{e \in E} buy_{p,e,t} = \sum_{e \in E} sell_{p,e,t}, \quad \forall p \in P, \forall t \in T$$

### 4.5 Inter-Exchange Transfer Activation & Lag Dynamics
$$send_{a,e_1,e_2,t} \le M_{\text{xf}} \cdot z_{a,e_1,e_2,t}, \quad \forall a, e_1 \ne e_2, t$$
$$\text{Outflow}_{a,e,t} = \sum_{e' \ne e} \left( send_{a,e,e',t} + F_{a,e,e'}^{\text{tx}} \cdot z_{a,e,e',t} \right)$$
$$\text{Inflow}_{a,e,t} = \sum_{e' \ne e \mid t - L_{a,e',e} \ge 1} send_{a,e',e,t - L_{a,e',e}}$$

### 4.6 Inventory Balance Tracking

#### Cash (USDT) Balance
$$inv_{\text{USDT},e,t} = inv_{\text{USDT},e,t-1} - \sum_p Pr_{p,e,t} \cdot buy_{p,e,t} \cdot (1 + \beta + \phi_e^{\text{buy}}) + \sum_p Pr_{p,e,t} \cdot sell_{p,e,t} \cdot (1 - \beta - \phi_e^{\text{sell}}) + \text{Inflow}_{\text{USDT},e,t} - \text{Outflow}_{\text{USDT},e,t}$$

#### Base Asset Balance (BTC / ETH)
$$inv_{a,e,t} = inv_{a,e,t-1} + buy_{a,e,t} - sell_{a,e,t} + \text{Inflow}_{a,e,t} - \text{Outflow}_{a,e,t}, \quad \forall a \in \{\text{BTC}, \text{ETH}\}$$

---

## 5. Objective Function (Marked-to-Market Terminal Capital)

$$\text{Maximise } Z = \sum_{e \in E} inv_{\text{USDT},e,N_T} + \sum_{a \in \{\text{BTC},\text{ETH}\}} \bar{Pr}_{a,N_T} \sum_{e \in E} \left( inv_{a,e,N_T} - I_{a,e,0} \right) - \sum_{e \in E} I_{\text{USDT},e,0}$$

---

## 6. Daily Independent Windows

Each trading day (2026-10-02 through 2026-10-08) is solved as an independent 24-hour optimization window ($N_T = 48$ steps at 30-min resolution) starting from initial inventory $I_{a,e,0}$. Total 7-day profit is the exact sum of daily window objectives.
