"""
Local entry point for `backtest_from_csv.py`. The canonical strategy lives in
`prosperity_submission.py` — that is the file to paste or upload to Prosperity.
"""

from prosperity_submission import Trader

__all__ = ["Trader"]
