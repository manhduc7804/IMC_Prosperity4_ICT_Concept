import csv
import statistics
from collections import defaultdict


def load_mids(path: str, product: str) -> list[float]:
    by_ts: dict = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            ts = int(row["timestamp"])
            by_ts[ts][row["product"]] = row
    out: list[float] = []
    for ts in sorted(by_ts.keys()):
        if product not in by_ts[ts]:
            continue
        mp = by_ts[ts][product].get("mid_price", "").strip()
        if mp:
            out.append(float(mp))
    return out


def oracle_pnl(mids: list[float], fade: bool, k: float, win: int) -> float:
    pnl = 0.0
    r = [mids[i] - mids[i - 1] for i in range(1, len(mids))]
    for i in range(win + 1, len(mids) - 1):
        sig = statistics.stdev(r[i - win : i])
        if sig < 1e-9:
            continue
        pr = r[i - 1]
        if fade:
            pred = -pr
            if pred > k * sig:
                pnl += mids[i + 1] - mids[i]
            elif pred < -k * sig:
                pnl += mids[i] - mids[i + 1]
        else:
            if pr > k * sig:
                pnl += mids[i + 1] - mids[i]
            elif pr < -k * sig:
                pnl += mids[i] - mids[i + 1]
    return pnl


if __name__ == "__main__":
    path = "prices_round_1_day_0.csv"
    for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        mids = load_mids(path, prod)
        best = (-1e18, None)
        for fade in (True, False):
            for k in (0.5, 1.0, 1.5, 2.0, 2.5):
                for win in (20, 50, 100, 150):
                    p = oracle_pnl(mids, fade, k, win)
                    if p > best[0]:
                        best = (p, ("fade" if fade else "momo", k, win))
        print(prod, "oracle best", best)
