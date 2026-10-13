# DATA DICTIONARY: MILP ARBITRAGE DATASET PACKAGE

## Primary Dataset: `milp_master.csv`
- **Rows:** 141,120 rows (10,080 minutes per pair and exchange across 7 exchanges for BTC/USDT and ETH/USDT).
- **Time Horizon:** 2026-10-02T00:00:00Z to 2026-10-09T00:00:00Z exclusive (7 FULL UTC Days).

| Column Name | Data Type | Units | Description | Provenance / Source |
| :--- | :--- | :--- | :--- | :--- |
| `ts` | String | ISO UTC | UTC Timestamp formatted as `%Y-%m-%dT%H:%M:%SZ` | Exchange OHLCV timestamp |
| `pair` | String | N/A | Standard trading pair (`BTC/USDT` or `ETH/USDT`) | Project config |
| `exchange` | String | N/A | Exchange venue ID (`binance, coinbase, kucoin, bitfinex, bybit, htx, cryptocom`) | Exchange API |
| `quote_ccy` | String | N/A | Native quote currency (`USDT` for spot, `USD` for Coinbase) | Exchange API |
| `open` | Float | Quote Ccy | Opening price of 1-minute candle | Raw 1m candle |
| `high` | Float | Quote Ccy | Highest price in 1-minute candle | Raw 1m candle |
| `low` | Float | Quote Ccy | Lowest price in 1-minute candle | Raw 1m candle |
| `close` | Float | Quote Ccy | Closing price of 1-minute candle | Raw 1m candle |
| `volume` | Float | Base Asset | Trading volume in 1-minute candle | Raw 1m candle |
| `close_usdt_equiv` | Float | USDT | USDT-equivalent close price (`close / usdt_usd_close` for Coinbase) | Computed via Coinbase USDT/USD |
| `is_filled` | Boolean | Flag | True if minute was missing in raw API and forward-filled | Data cleaning (`ffill` only) |
| `age_min` | Integer | Minutes | Consecutive minutes since last real raw candle | Data cleaning counter |
| `is_zero_volume` | Boolean | Flag | True if `volume == 0.0` | Data cleaning flag |
| `is_flat_candle` | Boolean | Flag | True if `open == high == low == close` | Data cleaning flag |
| `is_stale` | Boolean | Flag | True if `age_min >= 5` | Data cleaning flag |
| `is_outlier` | Boolean | Flag | True if `close_usdt_equiv` > 5.0% from cross-exchange median | Data cleaning flag |
| `tradable` | Boolean | Flag | True if `not is_filled and volume > 0.0` | Trade execution mask |
| `taker_fee_pct` | Float | % | Base-tier spot taker fee percentage | Exchange fee schedule |
| `maker_fee_pct` | Float | % | Base-tier spot maker fee percentage | Exchange fee schedule |
| `fee_source_type` | String | Label | Parameter provenance (`fetched_api, assumption, missing`) | Provenance audit |
| `fee_source_file` | String | Path/URL | Raw JSON file or official exchange fee page URL | Provenance audit |
| `min_qty` | Float | Base Asset | Minimum order quantity per trade | Exchange market rules |
| `qty_step` | Float | Base Asset | Quantity step size / precision | Exchange market rules |
| `min_notional` | Float | Quote Ccy | Minimum order notional value (USDT or USD) | Exchange market rules |
| `price_tick` | Float | Quote Ccy | Minimum price tick size / precision | Exchange market rules |
| `market_source_type` | String | Label | Parameter provenance (`fetched_api`) | Provenance audit |
| `market_source_file` | String | Path | Raw API response JSON file | Provenance audit |

---

## Known Dataset Limitations

1. **Cross-Exchange Timing Artifacts:** 1-minute close prices reflect the last trade executed within each 60s window. Execution timing across venues can differ by up to ~59 seconds, generating artificial spread spikes.
2. **Order Book Depth:** Historical order book depth is not available historically. Order book depth slippage is modeled as an empirical spread buffer derived from live order book sampling (`slippage_calibration.csv`).
3. **On-Chain Transfer Delays:** On-chain transfer delays (BTC ~60 min, ETH ~3 min) exceed 1-minute candle windows. MILP decision variables must model transfers as discrete lag steps $L$.
4. **Coinbase USD Conversion:** Coinbase trades BTC/USD and ETH/USD. Converted via Coinbase 1m USDT/USD candles. Mean absolute peg deviation is 0.0301%.
