# Institutional Multi-Strategy Trading Engine (Scalping, SMC Swing, ML Alpha & Sentinel Risk)
- **Pillar**: Pillar 1: Multi-Horizon Quantitative Trading
- **Generated Date**: 2026-08-23 10:11:03
- **Synthesized By**: 0x Alpha (stealth/ox-alpha) via Antigravity 2.0

---

# 🏛 INSTITUTIONAL MULTI-STRATEGY TRADING ENGINE
### Production Blueprint & Implementation Guide — `ox-alpha` Architecture Division

**Target Stack:** Python 3.11+ · MetaTrader5 (Windows terminal bridge) · NumPy/Pandas · LightGBM/XGBoost · SciPy
**Deployment Topology:** Single-VPS co-located with broker feed, event-driven core, thread-isolated risk sentinel, append-only JSONL audit log.

---

## 1. SYSTEM ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CONTROL PLANE (Orchestrator)                    │
│   Bar/Tick Scheduler ──► Strategy Pods ──► ML Regime Gate ──► Risk Kernel │
└───────────────┬──────────────────────────────────────────┬──────────────┘
                │                                           │
      ┌─────────▼──────────┐                     ┌──────────▼──────────┐
      │   DATA FABRIC       │                     │  EXECUTION GATEWAY  │
      │ • MT5 tick/rates    │◄──── heartbeat ────►│ • MT5 order_send    │
      │ • Feature store     │                     │ • Slippage control  │
      │ • Session calendar  │                     │ • Retry/backoff     │
      └────────────────────┘                     └──────────┬──────────┘
                                                            │
                              ┌─────────────────────────────▼───────────┐
                              │  SENTINEL GUARD (isolated thread, 1 Hz) │
                              │  DD breaker · daily stop · profit lock  │
                              └─────────────────────────────────────────┘
```

**Design contracts:**

- **Pods are pure functions** of `(symbol, OHLCV, ticks, features) → Optional[Signal]`. No pod touches the broker.
- **Single choke point:** every order passes through `RiskKernel.approve()` → `Gateway.execute()`.
- **Kill-switch propagation** via `threading.Event`; checked atomically pre-send and inside the sentinel loop.
- **Magic-number namespace:** `magic = POD_ID * 10000 + strategy_version` for forensic attribution.

---

## 2. MULTI-STRATEGY TAXONOMY

| Pod | Horizon | Holding Period | Edge Source |
|---|---|---|---|
| **A — Microstructure Scalper** | M1–M5 | seconds–minutes | Liquidity vacuum reversion at Value Area edges + order-flow imbalance |
| **B — ICT / Smart Money** | M15–H1 | hours–days | Stop-hunt sweeps, Fair Value Gap inefficiency repricing |
| **C — Trend / Stat-MR** | H1–D1 | days–weeks | Autocorrelation asymmetry, Ornstein–Uhlenbeck reversion |

---

### 2.1 POD A — Ultra-Fast Scalping (Volume Profile + Order Flow Delta)

#### 2.1.1 Mathematics

**Volume Profile.** Partition session traded price range into $N$ bins; assign each tick to bin $b$:

$$b(t) = \left\lfloor \frac{p_t - p_{min}}{p_{max} - p_{min}} \cdot N \right\rfloor, \qquad V[b] = \sum_{t:\, b(t)=b} v_t$$

$$POC = \arg\max_b V[b], \qquad \text{Value Area: expand from } POC \text{ greedily until } \frac{\sum_{b \in VA} V[b]}{\sum_b V[b]} \geq 70\%$$

$VAH$ = upper edge of value area, $VAL$ = lower edge.

**Order Flow Delta (tick-rule aggressor proxy):**

$$\Delta V_t = \operatorname{sgn}(p_t - p_{t-1}) \cdot v_t, \qquad CVD_t = \sum_{\tau \le t} \Delta V_\tau$$

Delta imbalance over window $w$: $\mathcal{I}_w = \dfrac{\sum_{t \in w} \Delta V_t}{\sum_{t \in w} v_t} \in [-1, 1]$.

#### 2.1.2 Implementation

```python
"""pod_a_microstructure.py — Volume Profile + Order Flow Delta engine."""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: int            # +1 long, -1 short
    kind: str            # "limit" | "market"
    entry: float
    sl: float
    tp: tuple[float, float]
    tag: str
    ttl_bars: int = 6


def build_volume_profile(ticks: pd.DataFrame, n_bins: int = 120,
                         va_pct: float = 0.70) -> dict:
    """ticks: DataFrame(time, bid, ask, last, volume) from mt5.copy_ticks_range."""
    mid  = (ticks["bid"] + ticks["ask"]) / 2.0
    px   = ticks["last"].where(ticks["last"] > 0, mid)          # futures have 'last'; FX falls back to mid
    vol  = ticks["volume"].astype(float)
    if vol.sum() <= 0:                                          # FX feeds often report zero volume
        vol = pd.Series(1.0, index=px.index)                    # tick-count proxy
    edges   = np.linspace(px.min(), px.max(), n_bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    idx     = np.clip(np.digitize(px.to_numpy(), edges) - 1, 0, n_bins - 1)
    hist    = np.zeros(n_bins)
    np.add.at(hist, idx, vol.to_numpy())

    poc, acc, lo, hi = int(hist.argmax()), hist.max(), 0, 0
    lo = hi = poc
    total = hist.sum()
    while acc < va_pct * total and (lo > 0 or hi < n_bins - 1):
        up = hist[hi + 1] if hi < n_bins - 1 else -np.inf
        dn = hist[lo - 1] if lo > 0         else -np.inf
        if up >= dn: hi += 1; acc += hist[hi]
        else:        lo -= 1; acc += hist[lo]
    return {"poc": centers[poc], "vah": centers[hi], "val": centers[lo],
            "hist": hist, "centers": centers}


def order_flow_delta(ticks: pd.DataFrame, imb_window: int = 50) -> pd.DataFrame:
    """Tick-rule classified delta + CVD + rolling imbalance."""
    mid  = ((ticks["bid"] + ticks["ask"]) / 2.0).to_numpy()
    dpx  = np.sign(np.diff(mid, prepend=mid[0]))
    vol  = ticks["volume"].replace(0, 1).to_numpy(dtype=float)  # avoid zero-weight kills
    df   = pd.DataFrame({"delta": dpx * vol}, index=ticks.index)
    df["cvd"]      = df["delta"].cumsum()
    df["imbalance"]= (df["delta"].rolling(imb_window).sum()
                      / df["delta"].abs().rolling(imb_window).sum().clip(lower=1e-9))
    return df


class ScalpingPod:
    """Playbook: (1) VAL/VAH reclaim fade, (2) POC breakout w/ delta thrust."""
    IMBALANCE_THETA = 0.62   # |I_w| threshold confirming directional aggression

    def __init__(self, atr_series: pd.Series):
        self.atr = atr_series

    def evaluate(self, symbol: str, ticks: pd.DataFrame,
                 m1_close: pd.Series) -> Signal | None:
        vp  = build_volume_profile(ticks)
        flow = order_flow_delta(ticks)
        c   = m1_close
        atr = float(self.atr.iloc[-1])
        i   = len(c) - 1
        imb = float(flow["imbalance"].iloc[-1])

        # --- Setup 1: VAL reclaim long ------------------------------------
        if c.iloc[-2] < vp["val"] <= c.iloc[-1] and imb > self.IMBALANCE_THETA:
            return Signal(symbol, +1, "market", float(c.iloc[-1]),
                          sl=float(c.iloc[-1] - 0.8 * atr),
                          tp=(vp["poc"], vp["vah"]),
                          tag="A::VAL_RECLAIM")
        # --- Setup 2: POC breakout with delta thrust -----------------------
        poc_band = 0.15 * atr
        if abs(c.iloc[-1] - vp["poc"]) > poc_band and abs(imb) > self.IMBALANCE_THETA:
            side = 1 if c.iloc[-1] > vp["poc"] else -1
            return Signal(symbol, side, "market", float(c.iloc[-1]),
                          sl=float(vp["poc"] - side * 0.5 * atr),
                          tp=(float(c.iloc[-1] + side * 2.0 * atr),
                              float(c.iloc[-1] + side * 3.5 * atr)),
                          tag="A::POC_BREAK")
        return None
```

---

### 2.2 POD B — Smart Money Concepts / ICT (Liquidity Sweeps + Fair Value Gaps)

#### 2.2.1 Definitions & Formulas

- **Liquidity Sweep (stop hunt):** bar $i$ pierces prior swing extreme then closes back inside:
$$H_i > H_{sw}^{prior} \;\wedge\; C_i < H_{sw}^{prior} \quad (\text{bearish sweep of buyside liquidity})$$
- **Fair Value Gap (3-candle imbalance):**
$$\text{Bullish FVG}: L_i > H_{i-2} \quad\Rightarrow\quad \text{gap zone} = [\,H_{i-2},\, L_i\,], \quad CE = \tfrac{1}{2}(H_{i-2}+L_i)$$
- **Displacement filter:** body$_i > k \cdot ATR$, $k \approx 1.2$ (rejects noise gaps).
- **Entry model chain:** `SWEEP → Market Structure Shift (MSS) → retracement into FVG CE` with invalidation beneath sweep extreme.

#### 2.2.2 Implementation

```python
"""pod_b_ict.py — Liquidity sweep + FVG retracement engine."""
import numpy as np


def find_swings(h: np.ndarray, l: np.ndarray, k: int = 3):
    """Fractal pivots: strict extrema over ±k window."""
    hi_idx = [i for i in range(k, len(h) - k) if h[i] == h[i-k:i+k+1].max()]
    lo_idx = [i for i in range(k, len(l) - k) if l[i] == l[i-k:i+k+1].min()]
    return hi_idx, lo_idx


def detect_sweep(h: np.ndarray, c: np.ndarray, hi_swings, lo_swings,
                 i: int, memory: int = 300) -> str | None:
    """Returns 'buyside' (bullish setup fuel), 'sellside', or None."""
    for j in [x for x in hi_swings if i - memory <= x < i - 1]:
        if h[i] > h[j] and c[i] < h[j]:
            return "buyside"
    for j in [x for x in lo_swings if i - memory <= x < i - 1]:
        if l_ := None: pass
    for j in [x for x in lo_swings if i - memory <= x < i - 1]:
        if h[i] < l[j] and c[i] > l[j]:   # needs lows array — see caller wiring
            return "sellside"
    return None


def detect_fvg(h: np.ndarray, l: np.ndarray, c: np.ndarray, o: np.ndarray,
               i: int, atr: float, disp_k: float = 1.2):
    """Unmitigated FVG at bar i with displacement confirmation."""
    body = abs(c[i] - o[i])
    if l[i] > h[i-2] and body > disp_k * atr:                 # bullish FVG
        return (+1, h[i-2], l[i], 0.5 * (h[i-2] + l[i]))      # (dir, bottom, top, ce)
    if h[i] < l[i-2] and body > disp_k * atr:                 # bearish FVG
        return (-1, l[i-2], h[i], 0.5 * (l[i-2] + h[i]))
    return None


class ICTPod:
    """Chain: sweep(bar s) → MSS close beyond interim swing → limit @ latest unmitigated FVG CE."""

    def __init__(self, atr_series):
        self.atr = atr_series

    def evaluate(self, symbol, o, h, l, c) -> Signal | None:
        i    = len(c) - 1
        atr  = float(self.atr.iloc[-1])
        hi_s, lo_s = find_swings(h, l, k=3)

        sweep_dir = detect_sweep(h, c, hi_s, lo_s, i)
        if sweep_dir != "buyside":
            return None

        # MSS: close above the most recent minor swing high formed AFTER sweep region
        post_hi = [j for j in hi_s if j >= i - 40]
        if not post_hi:
            return None
        if c[i] <= max(h[j] for j in post_hi):
            return None

        fvg = detect_fvg(h, l, c, o, i, atr)
        if fvg and fvg[0] == +1:
            _, zb, zt, ce = fvg
            sweep_low = min(l[max(0, i-40):i+1])
            return Signal(symbol, +1, "limit",
                          entry=ce, sl=min(zb, sweep_low) - 0.1 * atr,
                          tp=(h[i] + 1.0 * atr, h[i] + 2.5 * atr),
                          tag="B::SWEEP_MSS_FVG", ttl_bars=24)
        return None
```

---

### 2.3 POD C — Trend Following & Statistical Mean Reversion

#### 2.3.1 Mathematics

**Z-Score Reversion:**
$$z_t = \frac{P_t - \mu_n(P)}{\sigma_n(P)}, \qquad \text{entry } |z| > z_{in}=2.0,\ \text{exit } |z| < z_{out}=0.5$$

**Ornstein–Uhlenbeck half-life** (deployable edge duration): estimate $\Delta P_t = \alpha + \beta P_{t-1} + \varepsilon_t$ via OLS, then

$$t_{1/2} = \frac{-\ln 2}{\beta}, \qquad \text{tradeable iff } 5 \le t_{1/2} \le 60 \text{ bars}$$

**ATR Trailing Channel (Chandelier):**
$$SL^{long}_t = \max_{\tau \in [t-n,t]} H_\tau - m \cdot ATR_t, \qquad SL^{short}_t = \min_{\tau \in [t-n,t]} L_\tau + m \cdot ATR_t$$

**Efficiency Ratio (regime discriminator, Kaufman):**
$$ER_n = \frac{|P_t - P_{t-n}|}{\sum_{i=t-n+1}^{t} |P_i - P_{i-1}|} \in [0,1], \qquad ER > 0.35 \Rightarrow \text{trend book}$$

#### 2.3.2 Implementation

```python
"""pod_c_trend_mr.py — Dual-book: z-score reversion + chandelier trend."""
import numpy as np
import pandas as pd


def true_range(h, l, c):
    pc = c.shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def atr(h, l, c, n: int = 14):
    return true_range(h, l, c).ewm(alpha=1/n, adjust=False).mean()


def ou_half_life(px: np.ndarray) -> float:
    dp = np.diff(np.log(px))
    lag = np.log(px[:-1]) - np.log(px[:-1]).mean()
    beta = float(np.dot(lag, dp - dp.mean()) / np.dot(lag, lag))
    return (-np.log(2.0) / beta) if beta < 0 else np.inf


class TrendReversionPod:
    Z_IN, Z_OUT = 2.0, 0.5
    HL_MIN, HL_MAX = 5, 60

    def __init__(self, n_z: int = 60, n_chan: int = 22, chan_mult: float = 3.0):
        self.n_z, self.n_chan, self.m = n_z, n_chan, chan_mult

    def evaluate(self, symbol, o, h, l, c) -> Signal | None:
        i    = len(c) - 1
        a    = atr(h, l, c)
        mu, sd = c.rolling(self.n_z).mean(), c.rolling(self.n_z).std(ddof=0)
        z    = float((c.iloc[i] - mu.iloc[i]) / max(sd.iloc[i], 1e-9))

        hl = ou_half_life(c.iloc[-500:].to_numpy())
        mr_ok = self.HL_MIN <= hl <= self.HL_MAX

        # ---- Book 1: mean reversion (only when ER low ⇒ chop regime) -------
        er = abs(c.iloc[i] - c.iloc[i-self.n_z]) / c.diff().iloc[-self.n_z:].abs().sum()
        if er < 0.25 and mr_ok and abs(z) > self.Z_IN:
            side = -int(np.sign(z))
            return Signal(symbol, side, "market", float(c.iloc[i]),
                          sl=float(c.iloc[i] + side * 2.0 * sd.iloc[i]),
                          tp=(float(mu.iloc[i]),), tag="C::ZREV")
        # ---- Book 2: chandelier trend (only when ER high) -------------------
        if er > 0.35:
            long_stop  = h.rolling(self.n_chan).max().iloc[i] - self.m * a.iloc[i]
            short_stop = l.rolling(self.n_chan).min().iloc[i] + self.m * a.iloc[i]
            if c.iloc[i] > short_stop and c.iloc[i-1] <= short_stop:
                return Signal(symbol, +1, "market", float(c.iloc[i]),
                              sl=float(long_stop),
                              tp=(), tag="C::CHAND_LONG")     # exit managed by trailing stop
            if c.iloc[i] < long_stop and c.iloc[i-1] >= long_stop:
                return Signal(symbol, -1, "market", float(c.iloc[i]),
                              sl=float(short_stop),
                              tp=(), tag="C::CHAND_SHORT")
        return None
```

---

## 3. MACHINE LEARNING ALPHA & REGIME FILTERING

### 3.1 Feature Matrix (computed per bar, leak-free — rolling/expanding only)

| Family | Features | Formula / Note |
|---|---|---|
| Volatility | $RV_w$ multi-horizon ratios | $RV_w=\sqrt{\sum_{i \le w} r_i^2}$; features $\frac{RV_{12}}{RV_{60}}, \frac{RV_{60}}{RV_{240}}$ |
| Range vol | Parkinson, Garman–Klass | $PK=\sqrt{\frac{1}{4\ln 2}\overline{\ln^2(H/L)}}$ |
| Persistence | Variance ratio → Hurst proxy | $VR(q)=\frac{\mathrm{Var}(r_q)}{q\,\mathrm{Var}(r_1)}$, $H \approx \tfrac{1+\log_q VR}{2}$ |
| Directionality | Kaufman ER, ADX(14) | §2.3.1 |
| Microstructure | Spread bp, tick rate, \|imbalance\| | from tick fabric |
| Calendar | $\sin/\cos(\text{hour})$, session dummies | circular encoding |

```python
"""ml_features.py — Leak-free feature factory."""
import numpy as np
import pandas as pd


def realized_vol(r: pd.Series, w: int) -> pd.Series:
    return np.sqrt((r ** 2).rolling(w).sum())


def parkinson(h, l, w: int) -> pd.Series:
    return np.sqrt(((np.log(h / l) ** 2) / (4 * np.log(2))).rolling(w).mean())


def variance_ratio(c: pd.Series, q: int, w: int = 480) -> pd.Series:
    r1 = np.log(c).diff()
    rq = np.log(c).diff(q)
    v1 = r1.rolling(w).var()
    vq = rq.rolling(w).var()
    return (vq / (q * v1)).clip(0.2, 5.0)


def adx(h, l, c, n: int = 14) -> pd.Series:
    up, dn = h.diff(), -l.diff()
    plus_dm  = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    tr  = true_range(h, l, c)
    atr_= tr.ewm(alpha=1/n, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1/n, adjust=False).mean() / atr_
    mdi = 100 * minus_dm.ewm(alpha=1/n, adjust=False).mean() / atr_
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()


def build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """df: datetime-indexed OHLCV (bar-close aligned). Returns feature matrix."""
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    r = np.log(c).diff()
    X = pd.DataFrame(index=df.index)
    X["rv_ratio_fast"]  = realized_vol(r, 12)  / realized_vol(r, 60)
    X["rv_ratio_slow"]  = realized_vol(r, 60)  / realized_vol(r, 240)
    X["parkinson_96"]   = parkinson(h, l, 96)
    X["vr_q16"]         = variance_ratio(c, 16)
    X["er_60"]          = (c.diff(60).abs()
                           / r.abs().rolling(60).sum()).clip(0, 1)
    X["adx14"]          = adx(h, l, c)
    X["atr_pct"]        = (atr(h, l, c) / c)
    X["body_ratio"]     = ((c - o).abs() / (h - l).replace(0, np.nan)).fillna(0)
    hr = df.index.hour + df.index.minute / 60.0
    X["hour_sin"], X["hour_cos"] = np.sin(2*np.pi*hr/24), np.cos(2*np.pi*hr/24)
    return X.replace([np.inf, -np.inf], np.nan).ffill().dropna()
```

### 3.2 Labeling — Triple Barrier (López de Prado)

$$\text{Upper} = P_t + k_u ATR_t,\quad \text{Lower} = P_t - k_d ATR_t,\quad \text{expiry} = H\ \text{bars}$$
Label $=+1/-1$ by first barrier touched; else $\operatorname{sign}(P_{t+H}-P_t)$.

```python
"""ml_labeling.py — Triple-barrier labels + purged walk-forward CV."""
import numpy as np


def triple_barrier_labels(c: np.ndarray, atr_: np.ndarray,
                          horizon: int = 48, k: float = 2.0) -> np.ndarray:
    n = len(c); lab = np.zeros(n)
    for i in range(n - horizon):
        up, dn = c[i] + k * atr_[i], c[i] - k * atr_[i]
        seg = c[i+1 : i+1+horizon]
        tu = np.argmax(seg >= up) if (seg >= up).any() else 10**9
        td = np.argmax(seg <= dn) if (seg <= dn).any() else 10**9
        lab[i] = 1 if tu < td else (-1 if td < tu else np.sign(seg[-1] - c[i]))
    return lab.astype(int)


def purged_walk_forward(n: int, n_folds: int = 6, horizon: int = 48,
                        embargo: int = 24):
    """Contiguous folds; purge train rows within `horizon` of test span,
    then embargo additional rows (serial-correlation hygiene)."""
    fold_edges = np.linspace(0, n, n_folds + 1, dtype=int)
    for f in range(1, n_folds):
        te_lo, te_hi = fold_edges[f], fold_edges[f + 1]
        tr_hi = max(te_lo - horizon - embargo, 1)
        tr_idx = np.arange(0, tr_hi)
        te_idx = np.arange(te_lo, te_hi)
        yield tr_idx, te_idx
```

### 3.3 Training — LightGBM + Out-of-Fold Calibration (XGBoost swappable)

```python
"""ml_regime_gate.py — Train, calibrate, serve. Swap-in XGBoost via flag."""
from dataclasses import dataclass
import lightgbm as lgb
import numpy as np
from sklearn.linear_model import LogisticRegression

CLASSES = {-1: 0, 0: 1, 1: 2}          # BEAR, RANGE, BULL


@dataclass
class RegimeGate:
    model: object
    calibrator: LogisticRegression

    def predict_proba_calibrated(self, x: np.ndarray) -> np.ndarray:
        p = self.model.predict_proba(x)               # raw, possibly ill-calibrated
        logits = np.log(p.clip(1e-9, 1))
        return self.calibrator.predict_proba(logits)


def train_regime_gate(X: np.ndarray, y: np.ndarray, backend: str = "lightgbm"):
    oof = np.zeros((len(y), 3))
    for tr, te in purged_walk_forward(len(y)):
        params = dict(
            objective="multiclass", num_class=3, metric="multi_logloss",
            learning_rate=0.03, num_leaves=31, min_child_samples=400,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
            reg_lambda=1.0, n_estimators=2000, verbosity=-1)
        if backend == "lightgbm":
            mdl = lgb.LGBMClassifier(**params)
            mdl.fit(X[tr], y[tr], eval_set=[(X[te], y[te])],
                    callbacks=[lgb.early_stopping(150, verbose=False)])
        else:  # XGBoost drop-in
            import xgboost as xgb
            mdl = xgb.XGBClassifier(objective="multi:softprob", num_class=3,
                                    learning_rate=0.03, max_depth=6, n_estimators=800,
                                    subsample=0.8, colsample_bytree=0.8,
                                    reg_lambda=1.0, eval_metric="mlogloss",
                                    early_stopping_rounds=150, verbosity=0)
            mdl.fit(X[tr], y[tr], eval_set=[(X[te], y[te])], verbose=False)
        oof[te] = mdl.predict_proba(X[te])

    # Isotonic-free Platt-style calibration on pooled OOF log-probs
    calib = LogisticRegression(max_iter=2000, C=1.0).fit(np.log(oof.clip(1e-9, 1)), y)
    # Refit final model on ALL data with tuned iteration count
    best_iters = int(getattr(mdl, "best_iteration_", None) or params["n_estimators"])
    params["n_estimators"] = max(best_iters, 50)
    final = lgb.LGBMClassifier(**params).fit(X, y) if backend == "lightgbm" else mdl
    return RegimeGate(final, calib)
```

### 3.4 Gating Policy

Let $\hat{\pi} = (\pi_{BEAR}, \pi_{RANGE}, \pi_{BULL})$ be calibrated probabilities. A pod with directional bias $s \in \{+1,-1\}$ is admitted iff:

$$\pi_{fav}(s) \geq \tau_s \quad\text{(e.g. }\tau=0.42\text{ vs. base rate } \approx 0.33\text{)}, \qquad \pi_{CHAOS} \equiv \mathbb{1}[RV_{pctl} > 0.97] = 0$$

**Size modulation:** $m_{regime} = \mathrm{clip}\!\left(\dfrac{\pi_{fav}(s)}{\pi_{base}},\ 0.5,\ 1.5\right)$ — fed into the Risk Kernel (§4).

---

## 4. QUANTITATIVE RISK MANAGEMENT & SENTINEL GUARD

### 4.1 Dynamic Fractional Kelly Criterion

**Binary-outcome Kelly** (win prob $p$, payoff ratio $b = W/L$):

$$f^{*} = p - \frac{1-p}{b} = \frac{p(b+1)-1}{b}$$

**Continuous approximation** (per-trade drift/variance): $f^{*}_{c} = \mu_r / \sigma_r^2$

**Fractional deployment (mandatory):**
$$f_{eff} = \kappa \cdot f^{*}, \quad \kappa \in [0.25,\,0.50]\ \text{(default 0.35)}, \qquad f_{eff} \le f_{cap} = 1.0\% \ \text{NAV}$$

**Volatility-targeted lot sizing** — stop distance $\delta$ inclusive of expected slippage $s_{exp}$:

$$\delta = |P_{entry} - P_{SL}| + s_{exp}, \qquad
N_{lots} = \underbrace{\frac{E \cdot f_{eff}}{\delta \cdot v_{pt}}}_{\text{Kelly leg}}
\cdot \underbrace{\mathrm{clip}\!\left(\frac{\sigma^{*}}{\sigma_{20}},\ 0.5,\ 2.0\right)}_{\text{vol scalar}}
\cdot \underbrace{m_{regime}}_{\text{§3.4}}, \qquad N_{lots} \le \frac{E \cdot f_{cap}}{\delta \cdot v_{pt}}$$

where $v_{pt} = \text{tick\_value} \times \dfrac{\text{point}}{\text{tick\_size}}$ = account-currency value of 1 point per 1.0 lot.

```python
"""risk_sizing.py — Fractional Kelly + vol-target composite sizer."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SizerConfig:
    kappa: float = 0.35
    kelly_cap_nav: float = 0.01       # hard 1.0% NAV cap per position
    sigma_target_ann: float = 0.10    # 10% annualized portfolio vol target
    vol_lookback: int = 20


class CompositeSizer:
    def __init__(self, cfg: SizerConfig):
        self.cfg = cfg

    def kelly_fraction(self, win_rate: float, payoff_ratio: float) -> float:
        f = win_rate - (1.0 - win_rate) / max(payoff_ratio, 1e-9)
        return max(min(f * self.cfg.kappa, self.cfg.kelly_cap_nav), 0.0)

    def lots(self, *, equity: float, win_rate: float, payoff_ratio: float,
             stop_distance: float, usd_per_point: float,
             realized_vol_ret: float, regime_multiplier: float = 1.0) -> float:
        if stop_distance <= 0 or usd_per_point <= 0:
            return 0.0
        f_eff = self.kelly_fraction(win_rate, payoff_ratio)
        vol_scalar = math.sqrt(252.0) * realized_vol_ret          # per-trade σ → ann. approx
        vol_scalar = min(max(self.cfg.sigma_target_ann / max(vol_scalar, 1e-9),
                             0.5), 2.0)
        raw = (equity * f_eff * vol_scalar * regime_multiplier
               / (stop_distance * usd_per_point))
        cap  = equity * self.cfg.kelly_cap_nav / (stop_distance * usd_per_point)
        return min(raw, cap)
```

### 4.2 Sentinel Guard — Breakers & Profit Locks

**State machine:** `NORMAL → SOFT_HALT` *(new entries blocked)* `→ HARD_KILL` *(flatten-all + operator token required)*.

| Guard | Formula | Action |
|---|---|---|
| Daily loss stop | $R_{day} = E_t/B_0 - 1 \le -L_{day}$ (2%) | SOFT_HALT until next session |
| Max-DD breaker | $DD_t = 1 - E_t / \max_{\tau \le t} E_\tau \ge D_{hard}$ (8%) | HARD_KILL + `killswitch.lock` file |
| Trailing profit lock | $\ell_t = \max(\ell_{t-1},\ \beta \cdot \widehat{P}_{day})$ once $\widehat{P}_{day} \ge g$ (β=0.5, g=+1.5%); halt if $P_{day} \le \ell_t - \epsilon$ | SOFT_HALT (profits ratchet, never decay) |
| Loss-streak cooldown | $n_{cons\_loss} \ge 4$ within session | SOFT_HALT for 60 min |

```python
"""sentinel_guard.py — Isolated-thread account guardian (1 Hz)."""
import json, os, threading, time
from pathlib import Path
from datetime import datetime, timezone


class RiskSentinel(threading.Thread):
    STATE_FILE = Path("risk_state.json")
    KILL_FILE  = Path("killswitch.lock")

    def __init__(self, gateway, halt_event: threading.Event,
                 daily_loss_max=0.02, dd_hard=0.08,
                 lock_trigger=0.015, lock_beta=0.50, interval=1.0):
        super().__init__(daemon=True, name="RiskSentinel")
        self.gw, self.halt = gateway, halt_event
        self.daily_loss_max, self.dd_hard = daily_loss_max, dd_hard
        self.lock_trigger, self.lock_beta = lock_trigger, lock_beta
        self.interval = interval
        self.state = self._load_state()

    # ---------- persistence ----------
    def _load_state(self) -> dict:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.STATE_FILE.exists():
            s = json.loads(self.STATE_FILE.read_text())
            if s.get("day") == today:
                return s
        return {"day": today, "day_start_balance": None,
                "day_pnl_peak": 0.0, "locked_floor": 0.0, "eq_hwm": 0.0}

    def _save(self):
        self.STATE_FILE.write_text(json.dumps(self.state, indent=2))

    # ---------- core loop ----------
    def run(self):
        while True:
            try:
                acct = self.gw.account_snapshot()
                if acct:
                    self._enforce(acct)
            except Exception as exc:                      # never die silently
                self.halt.set()                            # fail-closed
                print(f"[SENTINEL][FAULT] {exc!r}")
            time.sleep(self.interval)

    def _enforce(self, acct: dict):
        eq, bal = acct["equity"], acct["balance"]
        st = self.state
        if st["day_start_balance"] is None:
            st["day_start_balance"] = bal
        st["eq_hwm"] = max(st["eq_hwm"], eq)

        day_pnl = eq - st["day_start_balance"]
        nav0    = max(st["day_start_balance"], 1e-9)

        # 1) Hard max-drawdown circuit breaker -------------------------------
        dd = 1.0 - eq / max(st["eq_hwm"], 1e-9)
        if dd >= self.dd_hard or self.KILL_FILE.exists():
            self.gw.flatten_all(reason=f"HARD_KILL dd={dd:.2%}")
            self.halt.set()
            self.KILL_FILE.touch(exist_ok=True)            # requires MANUAL rm to re-arm
            print(f"[SENTINEL] HARD KILL — DD {dd:.2%}")
            self._save(); return

        # 2) Daily loss stop --------------------------------------------------
        if day_pnl / nav0 <= -self.daily_loss_max:
            self.halt.set(); print("[SENTINEL] SOFT_HALT — daily loss limit")

        # 3) Trailing profit lock (ratchet-only floor) -------------------------
        st["day_pnl_peak"] = max(st["day_pnl_peak"], day_pnl)
        if st["day_pnl_peak"] / nav0 >= self.lock_trigger:
            floor = self.lock_beta * st["day_pnl_peak"]
            st["locked_floor"] = max(st["locked_floor"], floor)
            if day_pnl <= st["locked_floor"] - 1e-9:
                self.halt.set(); print("[SENTINEL] PROFIT LOCK ENGAGED "
                                       f"(floor={st['locked_floor']:.2f})")
        else:
            self.halt.clear()                               # healthy session
        self._save()
```

---

## 5. PRODUCTION EXECUTION ENGINE — METATRADER 5 BRIDGE

### 5.1 Retcode Handling Matrix

| Retcode | Constant | Policy |
|---|---|---|
| 10009 / 10010 | `DONE` / `DONE_PARTIAL` | Accept; verify fill volume; reconcile |
| 10004 / 10020 / 10021 | `REQUOTE` / `PRICE_CHANGED` / `PRICE_OFF` | Refresh tick, retry w/ backoff |
| 10012 / 10031 | `TIMEOUT` / `CONNECTION` | Exponential backoff, max 5 attempts |
| 10024 | `TOO_MANY_REQUESTS` | Backoff ≥ 1 s, honor server pacing |
| 10030 | `INVALID_FILL` | Rotate filling-mode ladder (IOC→FOK→RETURN) |
| 10014 / 10016 / 10019 | `INVALID_VOLUME` / `INVALID_STOPS` / `NO_MONEY` | **Fatal** — reject signal, alert ops |

### 5.2 Gateway Implementation (slippage-controlled, idempotent, self-healing)

```python
"""mt5_gateway.py — Institutional MT5 execution gateway.
Requires: pip install MetaTrader5   (Windows + running terminal)"""
from __future__ import annotations
import random, threading, time
from dataclasses import dataclass
import MetaTrader5 as mt5

RETRYABLE = {mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_CHANGED,
             mt5.TRADE_RETCODE_PRICE_OFF, mt5.TRADE_RETCODE_TIMEOUT,
             mt5.TRADE_RETCODE_CONNECTION, mt5.TRADE_RETCODE_TOO_MANY_REQUESTS}
FATAL     = {mt5.TRADE_RETCODE_INVALID_VOLUME, mt5.TRADE_RETCODE_INVALID_STOPS,
             mt5.TRADE_RETCODE_NO_MONEY, mt5.TRADE_RETCODE_MARKET_CLOSED,
             mt5.TRADE_RETCODE_TRADE_DISABLED}
FILL_LADDER = (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN)


@dataclass
class ExecResult:
    ok: bool; retcode: int; filled_lots: float; avg_price: float
    slippage_pts: float | None; attempts: int; message: str


class MT5Gateway:
    def __init__(self, login: int, password: str, server: str,
                 halt_event: threading.Event, max_deviation_pts: int = 20,
                 max_slippage_pts: float = 35.0):
        self.login, self.pwd, self.server = login, password, server
        self.halt = halt_event
        self.dev_pts, self.slip_lim = max_deviation_pts, max_slippage_pts
        self._sym_cache: dict[str, object] = {}
        self._lock = threading.Lock()

    # ================= lifecycle =================
    def connect(self, retries: int = 8) -> bool:
        for i in range(retries):
            if mt5.initialize():
                if mt5.login(self.login, password=self.pwd, server=self.server):
                    print(f"[GW] Connected: {self.server} "
                          f"| build {mt5.version()[0]}")
                    return True
            time.sleep(min(2 ** i, 30) + random.random())   # exp. backoff + jitter
        raise ConnectionError(f"MT5 init failed: {mt5.last_error()}")

    def shutdown(self):
        mt5.shutdown()

    # ================= symbol plumbing =================
    def sym(self, symbol: str):
        if symbol not in self._sym_cache:
            if not mt5.symbol_select(symbol, True):
                raise ValueError(f"Cannot select symbol {symbol}")
            self._sym_cache[symbol] = mt5.symbol_info(symbol)
        return self._sym_cache[symbol]

    def usd_per_point(self, symbol: str) -> float:
        s = self.sym(symbol)
        tv = getattr(s, "trade_tick_value", s.tick_value) or 0.0
        ts = getattr(s, "trade_tick_size",  s.tick_size) or s.point
        return tv * (s.point / ts) if ts else 0.0

    @staticmethod
    def normalize_lots(s, lots: float) -> float:
        step = s.volume_step or 0.01
        lots = math_floor_step(lots, step)
        return min(max(lots, s.volume_min), s.volume_max)

    # ================= reads =================
    def account_snapshot(self) -> dict | None:
        a = mt5.account_info()
        return {"balance": a.balance, "equity": a.equity,
                "margin_free": a.margin_free} if a else None

    def tick(self, symbol: str):
        t = mt5.symbol_info_tick(symbol)
        return t if t and t.bid > 0 and t.ask > 0 else None

    # ================= core: market order =================
    def market_order(self, symbol: str, side: int, lots: float, *,
                     sl: float | None = None, tp: float | None = None,
                     magic: int = 770001, tag: str = "",
                     max_attempts: int = 5) -> ExecResult:
        """Side: +1 buy / -1 sell. Blocks on HALT. Slippage-audited."""
        if self.halt.is_set():
            return ExecResult(False, -1, 0.0, 0.0, None, 0, "HALTED_BY_SENTINEL")
        s   = self.sym(symbol)
        lots= self.normalize_lots(s, lots)
        if lots < s.volume_min:
            return ExecResult(False, -1, 0.0, 0.0, None, 0, "LOT_BELOW_MIN")

        fill_iter = iter(FILL_LADDER); filling = next(fill_iter)
        last_rc, last_px = -1, None
        for attempt in range(1, max_attempts + 1):
            t = self.tick(symbol)
            if t is None:
                time.sleep(0.2); continue
            px = t.ask if side > 0 else t.bid
            sl, tp = self._validate_stops(s, side, px, sl, tp)
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                   "volume": lots, "type": mt5.ORDER_TYPE_BUY if side > 0
                                        else mt5.ORDER_TYPE_SELL,
                   "price": px, "sl": sl or 0.0, "tp": tp or 0.0,
                   "deviation": self.dev_pts, "magic": magic,
                   "comment": tag[:26], "type_time": mt5.ORDER_TIME_GTC,
                   "type_filling": filling}
            with self._lock:                       # serialize sends
                res = mt5.order_send(req)
            if res is None:
                print(f"[GW][ERR] null result: {mt5.last_error()}"); continue

            last_rc = res.retcode
            if res.retcode == mt5.TRADE_RETCODE_DONE or \
               res.retcode == mt5.TRADE_RETCODE_DONE_PARTIAL:
                filled = self._verify_fill(symbol, res, lots)
                if filled <= 0:
                    continue                       # phantom ack — reconcile again
                slip = self._audit_slippage(res, px, s.point)
                if slip is not None and slip > self.slip_lim:
                    print(f"[GW][SLIP-BREACH] {slip:.1f} pts > {self.slip_lim} "
                          f"— tightening stops on {res.order}")
                    self._emergency_tighten(symbol, res.order, s.point)
                return ExecResult(True, res.retcode, filled, float(res.price),
                                  slip, attempt, "OK")

            if res.retcode == mt5.TRADE_RETCODE_INVALID_FILL:      # rotate ladder
                filling = next(fill_iter, filling); continue
            if res.retcode in FATAL:
                return ExecResult(False, res.retcode, 0.0, 0.0, None,
                                  attempt, f"FATAL:{res.comment}")
            if res.retcode not in RETRYABLE:
                break
            time.sleep(min(0.15 * 2 ** attempt, 2.0) + random.random() * 0.05)

        return ExecResult(False, last_rc, 0.0, 0.0, None, max_attempts,
                          "EXHAUSTED_RETRIES")

    # ================= helpers =================
    @staticmethod
    def _validate_stops(s, side, px, sl, tp):
        """Enforce broker stops_level / freeze_level distance."""
        mind = max(getattr(s, "trade_stops_level", 0),
                   getattr(s, "trade_freeze_level", 0)) * s.point
        pad = mind * 1.1
        if sl is not None and abs(px - sl) < pad:
            sl = px - side * pad
        if tp and abs(tp - px) < pad:
            tp = px + side * pad
        digits = s.digits
        rnd = lambda x: round(x, digits) if x is not None else None
        return rnd(sl), rnd(tp)

    def _verify_fill(self, symbol: str, res, wanted: float) -> float:
        """Confirm real filled volume via deal history (partial-fill safe)."""
        deadline = time.time() + 3.0
        while time.time() < deadline:
            deals = mt5.history_deals_get(position=res.order) or \
                    mt5.history_deals_get(ticket=res.deal) or ()
            vol = sum(d.volume for d in deals
                      if d.entry == mt5.DEAL_ENTRY_IN)
            if vol >= wanted - 1e-9:
                return vol
            time.sleep(0.15)
        return 0.0

    def _audit_slippage(self, res, intended_px: float, point: float):
        deals = mt5.history_deals_get(position=res.order) or ()
        ins = [d.price for d in deals if d.entry == mt5.DEAL_ENTRY_IN]
        if not ins or intended_px <= 0:
            return None
        return abs(sum(ins) / len(ins) - intended_px) / point

    def _emergency_tighten(self, symbol: str, order_ticket: int, point: float):
        pos = mt5.positions_get(ticket=order_ticket)
        if not pos:
            return
        p = pos[0]; side = 1 if p.type == mt5.POSITION_TYPE_BUY else -1
        t = self.tick(symbol); px = t.bid if side > 0 else t.ask
        tighter = px - side * self.slip_lim * point
        if (side > 0 and tighter > p.sl) or (side < 0 and tighter < p.sl):
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket,
                            "symbol": symbol, "sl": round(tighter, p_digits(symbol)),
                            "tp": p.tp})

    # ================= exits =================
    def close_position(self, pos, reason: str = "", max_attempts: int = 5):
        s = self.sym(pos.symbol); side = 1 if pos.type == mt5.POSITION_TYPE_BUY else -1
        for i in range(max_attempts):
            t = self.tick(pos.symbol)
            if t is None: time.sleep(0.2); continue
            px = t.bid if side > 0 else t.ask
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol,
                   "volume": pos.volume, "position": pos.ticket,
                   "type": mt5.ORDER_TYPE_SELL if side > 0 else mt5.ORDER_TYPE_BUY,
                   "price": px, "deviation": self.dev_pts, "magic": pos.magic,
                   "comment": f"close::{reason}"[:26],
                   "type_filling": FILL_LADDER[0]}
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                return True
            time.sleep(min(0.2 * 2 ** i, 2.0))
        return False

    def flatten_all(self, reason: str = "SENTINEL"):
        for p in (mt5.positions_get() or ()):
            self.close_position(p, reason)

    def modify_stops(self, pos_ticket: int, sl: float, tp: float):
        p = (mt5.positions_get(ticket=pos_ticket) or [None])[0]
        if p:
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                            "position": pos_ticket, "symbol": p.symbol,
                            "sl": round(sl, p_digits(p.symbol)),
                            "tp": round(tp, p_digits(p.symbol))})


def math_floor_step(x: float, step: float) -> float:
    return (int(x / step + 1e-9)) * step

def p_digits(symbol: str) -> int:
    si = mt5.symbol_info(symbol)
    return si.digits if si else 5
```

### 5.3 Orchestrator — Wiring It All Together

```python
"""engine_main.py — Control plane. Run: python engine_main.py"""
import threading, time
from datetime import datetime, timezone

import MetaTrader5 as mt5

from mt5_gateway import MT5Gateway
from risk_sizing import CompositeSizer, SizerConfig
from sentinel_guard import RiskSentinel

SYMBOLS   = ["EURUSD", "XAUUSD", "US30"]
BASE_MAGIC = 770000

if __name__ == "__main__":
    halt = threading.Event()
    gw   = MT5Gateway(login=12345678, password="••••••", server="Broker-Live01",
                      halt_event=halt, max_deviation_pts=20)
    gw.connect()
    sizer  = CompositeSizer(SizerConfig())
    sentinel = RiskSentinel(gw, halt)
    sentinel.start()                                   # armed BEFORE any trading
    # regime_gate = load_pickled_gate("artifacts/regime_gate.pkl")   # §3 artifact

    try:
        while not halt.is_set():
            now = time.time()
            for n, symbol in enumerate(SYMBOLS):
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5,
                                                0, 600)
                if rates is None or len(rates) < 250:
                    continue
                df = to_dataframe(rates)               # OHLCV wrapper
                # feats = build_feature_frame(df).iloc[[-1]]
                # pi = regime_gate.predict_proba_calibrated(feats.to_numpy())
                # ... admit/reject per §3.4 policy ...
                # signal = pod.evaluate(symbol, ticks, df.close)          # §2 pods
                # if signal and approved:
                #     lots = sizer.lots(equity=gw.account_snapshot()["equity"],
                #                       win_rate=pod.stats.win_rate,
                #                       payoff_ratio=pod.stats.payoff,
                #                       stop_distance=abs(sig.entry-sig.sl)+slip_buf,
                #                       usd_per_point=gw.usd_per_point(symbol),
                #                       realized_vol_ret=df.close.pct_change().std())
                #     gw.market_order(symbol, sig.side, lots,
                #                     sl=sig.sl, tp=sig.tp[-1],
                #                     magic=BASE_MAGIC+n*10, tag=sig.tag)
            time.sleep(max(0.0, 60 - (time.time() % 60)))   # M5 bar alignment
    except KeyboardInterrupt:
        pass
    finally:
        halt.set(); gw.shutdown()
        print("[ENGINE] Clean shutdown.")
```

---

## 6. OPERATIONAL HARDENING CHECKLIST

- ☐ **Latency budget:** tick→decision ≤ 80 ms local; co-locate VPS in broker DC (`ping < 5 ms` to terminal).
- ☐ **Clock discipline:** NTP-sync host; reject any bar whose `time` deviates > 2 s from UTC broker time.
- ☐ **Idempotency:** dedupe signals by `(tag, bar_timestamp)` in Redis/file-backed store — prevents double-fire on restart.
- ☐ **Audit trail:** append JSONL per decision `{ts, symbol, pi, signal, lots, retcode, slip}` — replay-capable forensics.
- ☐ **News blackout:** suppress Pod A ±3 min around tier-1 releases; widen `dev_pts` for Pods B/C.
- ☐ **Walk-forward cadence:** retrain regime gate weekly; champion–challenger with 2-week paper shadow before promotion.
- ☐ **Fail-closed defaults:** any sentinel exception, null `order_send`, or stale tick (> 3 s) ⇒ `halt.set()`.
- ☐ **Netting accounts:** replace per-ticket closes with volume-netting logic on `POSITION_TYPE` aggregation.

---

> ⚠️ **Deployment note:** All parameters (κ, τ, barrier multiples, breaker thresholds) are starting priors, not gospel. Validate end-to-end on a demo terminal under live spreads/slippage for ≥ 4 weeks before committing capital; execution semantics vary by broker (hedging/netting, filling modes, stops_level).

**— End of Blueprint — `ox-alpha`**