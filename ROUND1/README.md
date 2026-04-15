# Round 1 — Trading bot <Entirely vibe coding to test right now>

Python **`Trader`** for **Ash-coated Osmium** and **Intarian Pepper Root**.

---

### Uploading to Prosperity

Use **`prosperity_submission.py`**: open it, copy **everything**, and paste into their submission editor (or upload that single file if they allow it—use **their** filename if they require one, e.g. `trader.py`).

**Do not upload** `backtest_from_csv.py`, CSVs, `_research_signals.py`, or this README unless the instructions say to submit a full zip.

**`datamodel`** is provided on Prosperity; your file should keep `from datamodel import Order, OrderDepth, TradingState` like their template.

---

### On your laptop

| File | Purpose |
|------|--------|
| **`prosperity_submission.py`** | **Submission copy** — edit strategy here, then paste/upload. |
| **`trader_round1.py`** | Re-exports `Trader` so `python3 backtest_from_csv.py` still works. |
| **`datamodel.py`** | Local types so imports work offline. |
| **`backtest_from_csv.py`** | Optional local replay on capsule CSVs. |
| **`_research_signals.py`** | Optional; not for upload. |
| **`*.csv`** | Sample history for local replay only. |

### Detailed file map

- **`prosperity_submission.py`**  
  Main strategy implementation. Defines `Trader.run()` and contains the Round 1 logic (short-horizon fade/mean-reversion with volatility and spread gates, inventory controls, and `traderData` state persistence).

- **`trader_round1.py`**  
  Thin local entrypoint that re-exports `Trader` from `prosperity_submission.py`, so local tooling can import a stable module name.

- **`backtest_from_csv.py`**  
  Local replay/backtest runner. Reads CSV book/trade data, builds `TradingState`, runs your trader each timestamp, simulates matching, applies position-limit checks, and reports cash/position/equity.

- **`datamodel.py`**  
  Local compatibility types (`Order`, `OrderDepth`, `Trade`, `TradingState`, etc.) so strategy code runs outside the Prosperity runtime.

- **`_research_signals.py`**  
  Optional research helper for quick signal checks (fade vs momentum, different thresholds/windows). Useful for tuning, not for submission.

- **`Data/*.csv`**  
  Historical sample data used by local replay and research scripts.

```bash
cd "/path/to/ROUND1"
python3 backtest_from_csv.py
```

Match **`POSITION_LIMITS`** in `backtest_from_csv.py` to the wiki if you use it.

---

### What the bot does (short)

It **fades** large one-step mid moves (vs recent volatility and spread), with soft inventory caps. State is in **`traderData`** (JSON).

---

### Important

- Local replay is **simplified** vs the real engine.
- Rules (libraries, limits): **Prosperity wiki**.
