from datetime import date

import pandas as pd


def draws_df(rows, supps=None):
    """Build a draws DataFrame from [(iso_date, [6 numbers]), ...]."""
    recs = []
    for i, (d, nums) in enumerate(rows):
        rec = {"draw_date": date.fromisoformat(d), **{f"n{j+1}": n for j, n in enumerate(sorted(nums))}}
        s = supps[i] if supps else (None, None)
        rec["supp1"], rec["supp2"] = s
        recs.append(rec)
    df = pd.DataFrame(recs)
    df["supp1"] = df["supp1"].astype("Int64")
    df["supp2"] = df["supp2"].astype("Int64")
    return df


# Four hand-checkable draws used across metric tests.
SMALL = draws_df(
    [
        ("2026-01-03", [1, 2, 3, 4, 5, 6]),
        ("2026-01-10", [1, 2, 3, 10, 20, 30]),
        ("2026-01-17", [7, 8, 9, 10, 20, 45]),
        ("2026-01-24", [1, 11, 22, 23, 40, 45]),
    ],
    supps=[(7, 8), (None, None), (1, 2), (2, 3)],
)
