---
name: oracle-quant-cycler
description: Zero-token autonomous quant telemetry reader, multi-timeframe analytics vault, and AI tuning routines for Oracle MAS on MT5.
---

# Oracle MAS — Autonomous Quant Cycler & AI Tuning Skill

This skill allows Antigravity to audit, analyze, and tune the **Oracle MAS (Multi-Agent Scalping Platform)** using ultra-efficient local telemetry files with minimal token consumption (<500 tokens for routine status checks).

---

## 🏗️ Architecture & Vault Structure

All heavy market calculations, tick audits, and multi-timeframe archiving run **100% locally on the user's PC via `autonomous_quant_cycler.py` (Zero API Cost)**.

### File Locations:
* **Realtime Compact Digest**: `c:\Users\deomo\oracle_mas\results\latest_quant_digest.json`
* **Analytics Vault Directory**: `c:\Users\deomo\oracle_mas\results\analytics_vault\`
  * 🕒 `hourly_snapshots/snapshot_YYYYMMDD_HH00.json`: Detailed 1-hour market & position state
  * 📅 `daily_summaries/daily_YYYYMMDD.json`: End-of-day equity curve, win/loss stats, top asset
  * 🗓️ `weekly_summaries/weekly_YYYY_Wxx.json`: 7-day regime shifts, profit factor drift
  * 📊 `monthly_summaries/monthly_YYYY_MM.json`: 30-day asset performance & macro trends
  * 🏛️ `quarterly_summaries/quarterly_YYYY_Qx.json`: 90-day seasonal performance & edge stability
  * 📈 `metrics_history.csv`: Continuous tabular time-series (ATR, RSI, EMAs, Equity, PnL)

---

## ⚡ 1. Ultra-Low-Token Status Audit (<500 Tokens)

When the user asks for account status, position update, or a routine check, **DO NOT run multi-step commands or query MT5 directly**. 
Simply view the compact digest file:

```python
# Path: c:\Users\deomo\oracle_mas\results\latest_quant_digest.json
```

Use `view_file` on this single JSON file. It contains:
- Account equity, balance, drawdown, margin level
- Open positions and live PnL
- Today's closed deal summary
- Top Alpha assets ranking
- Active breakout setups and anomaly alerts

---

## 🧠 2. Daily Behavior Tuning Routine (`daily_summaries`)

To analyze today's bot performance and tune intraday parameters:
1. Read `c:\Users\deomo\oracle_mas\results\analytics_vault\daily_summaries\daily_YYYYMMDD.json`.
2. Inspect the equity trajectory (`peak_equity` vs `trough_equity`).
3. Check `best_alpha_asset` and deal win rate.
4. **Actionable AI Recommendations**:
   - If drawdown > 1.5%: Tighten SL multipliers on Tier-4 bleeders (e.g. Gold/EURUSD).
   - If win rate > 65%: Increase allocation on the day's dominant alpha asset (e.g. USTECm).

---

## 📈 3. Weekly Edge & Regime Optimization (`weekly_summaries`)

To optimize parameters weekly:
1. Read the current ISO week file: `weekly_YYYY_Wxx.json`.
2. Compare start equity vs end equity.
3. Check Profit Factor across the 10 watched instruments.
4. **Actionable AI Recommendations**:
   - Adjust `SYMBOL_CONFIG` in `config/settings.py` for assets transitioning between trending and ranging regimes.
   - Adjust breakout thresholds if ATR has expanded or compressed.

---

## 🏛️ 4. Monthly & Quarterly Macro Tuning (`quarterly_summaries`)

To perform deep quantitative model tuning:
1. Read `quarterly_YYYY_Qx.json` and query `metrics_history.csv`.
2. Evaluate:
   - Long-term Sharpe Ratio & Maximum Favorable Excursion (MFE).
   - Stop Loss slippage and fill efficiency.
   - Machine learning model drift (XGBoost/GRU accuracy).
3. **Actionable AI Recommendations**:
   - Trigger model retraining via `RETRAIN.bat` if prediction accuracy drops below benchmark.
   - Update asset tier classifications in the Trade Journal.

---

## 🛠️ Daemon Management Commands

* **Start Autonomous Cycler**: `c:\Users\deomo\oracle_mas\START_AUTONOMOUS_CYCLER.bat` (Port 48897)
* **Start Live Plan Executor**: `c:\Users\deomo\oracle_mas\START_LIVE_EXECUTOR.bat` (Port 48898)
* **Start Hourly Trader**: `c:\Users\deomo\oracle_mas\START_HOURLY_BOT.bat` (Port 48899)
* **One-Shot Manual Test**: `C:\Users\deomo\miniconda3\envs\oracle_gpu\python.exe c:\Users\deomo\oracle_mas\autonomous_quant_cycler.py --once`
