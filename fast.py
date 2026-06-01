import argparse
import glob
import os
import concurrent.futures

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta


def extract_stock_name(filepath: str) -> str:
    return os.path.basename(filepath).split(".")[0].upper()


def ts_to_ord(ts: pd.Timestamp) -> np.int64:
    """Timestamp -> days-since-epoch int (matching datetime64[D] int encoding)."""
    return np.array([ts.to_datetime64()], dtype="datetime64[D]").astype(np.int64)[0]


def find_idx(dates_ord: np.ndarray, ts: pd.Timestamp) -> int:
    """Index of first trading day on or after ts, or -1 if beyond data."""
    j = int(np.searchsorted(dates_ord, ts_to_ord(ts), side="left"))
    return j if j < len(dates_ord) else -1


def process_file(filepath: str, years: int, multiple: float, yoy_threshold: float):
    stock_name = extract_stock_name(filepath)
    detail_rows = []
    summary_row = None

    df = pd.read_csv(filepath, header=0)
    df.columns = [c.strip().strip("<>") for c in df.columns]
    df["DATE"] = pd.to_datetime(df["DATE"], format="%Y%m%d", errors="coerce")
    df["CLOSE"] = pd.to_numeric(df["CLOSE"], errors="coerce")
    df = df.dropna(subset=["DATE", "CLOSE"])
    df = df[df["CLOSE"] > 0]
    if len(df) < 2:
        return detail_rows, summary_row

    df = df.sort_values("DATE").reset_index(drop=True)
    closes = df["CLOSE"].values
    dates_ord = df["DATE"].values.astype("datetime64[D]").astype(np.int64)
    n = len(df)

    # ------------------------------------------------------------------ #
    # STEP 1: Find EARLIEST qualifying window (closes[j] / closes[i] >= Y
    #         where j is the first trading day on/after date[i] + X years)
    # ------------------------------------------------------------------ #
    qual_i = qual_j = -1
    for i in range(n):
        j = find_idx(dates_ord, df["DATE"].iat[i] + relativedelta(years=years))
        if j == -1:
            break  # all later starts also have no valid target date
        if closes[j] / closes[i] >= multiple:
            qual_i, qual_j = i, j
            break

    if qual_i == -1:
        return detail_rows, summary_row

    q_start_ts    = df["DATE"].iat[qual_i]
    q_end_ts      = df["DATE"].iat[qual_j]
    q_start_price = closes[qual_i]
    q_end_price   = closes[qual_j]
    q_growth      = round(q_end_price / q_start_price, 4)

    # ------------------------------------------------------------------ #
    # STEP 2 & 3: Track annual YoY from qualified_start_date
    #             Stop when year_growth_percent < Z; don't record that year
    # ------------------------------------------------------------------ #
    prev_idx  = qual_i
    last_idx  = qual_i
    peak_mult = 1.0

    for year_num in range(1, 100_000):
        j = find_idx(dates_ord, df["DATE"].iat[prev_idx] + relativedelta(years=1))
        if j == -1:
            break

        yoy_mult = closes[j] / closes[prev_idx]
        yoy_pct  = (yoy_mult - 1) * 100

        if yoy_pct < yoy_threshold:
            break  # stop; do not record this year

        cum_mult  = closes[j] / q_start_price
        peak_mult = max(peak_mult, cum_mult)

        detail_rows.append({
            "stock_name":                             stock_name,
            "qualified_start_date":                   q_start_ts.strftime("%Y-%m-%d"),
            "qualified_end_date":                     q_end_ts.strftime("%Y-%m-%d"),
            "qualified_start_price":                  round(q_start_price, 6),
            "qualified_end_price":                    round(q_end_price, 6),
            "qualified_growth_multiple":              q_growth,
            "growth_year_number":                     year_num,
            "period_start_date":                      df["DATE"].iat[prev_idx].strftime("%Y-%m-%d"),
            "period_end_date":                        df["DATE"].iat[j].strftime("%Y-%m-%d"),
            "period_start_price":                     round(closes[prev_idx], 6),
            "period_end_price":                       round(closes[j], 6),
            "year_growth_multiple":                   round(yoy_mult, 4),
            "year_growth_percent":                    round(yoy_pct, 2),
            "cumulative_multiple_from_qualified_start": round(cum_mult, 4),
        })

        last_idx = j
        prev_idx = j

    # ------------------------------------------------------------------ #
    # STEP 4: Per-stock summary (included for all qualified stocks)
    # ------------------------------------------------------------------ #
    summary_row = {
        "stock_name":                stock_name,
        "qualified_start_date":      q_start_ts.strftime("%Y-%m-%d"),
        "growth_duration_years":     len(detail_rows),
        "qualified_growth_multiple": q_growth,
        "final_multiple":            round(closes[last_idx] / q_start_price, 4),
        "peak_multiple":             round(peak_mult, 4),
    }

    return detail_rows, summary_row


def main():
    parser = argparse.ArgumentParser(
        description="Qualify stocks by Yx growth in X years, then track annual YoY >= Z%%."
    )
    parser.add_argument("--data", default="/Users/df/Documents/stock/history/daily/us/**/*.txt",
                        help="Glob pattern for stock .txt files (recursive)")
    parser.add_argument("--years", type=int, default=3,
                        help="Qualification window in calendar years (default: 3)")
    parser.add_argument("--multiple", type=float, default=10.0,
                        help="Minimum growth multiple for qualification (default: 10.0)")
    parser.add_argument("--yoy_threshold", type=float, default=30.0,
                        help="Minimum annual YoY growth %% to continue tracking (default: 30.0)")
    parser.add_argument("--output_detail", default=None,
                        help="Detail CSV path (auto-named if omitted)")
    parser.add_argument("--output_summary", default=None,
                        help="Summary CSV path (auto-named if omitted)")
    parser.add_argument("--progress", type=int, default=500,
                        help="Print progress every N files (default: 500)")
    args = parser.parse_args()

    tag          = f"{args.years}yr_{int(args.multiple)}x_{int(args.yoy_threshold)}pct"
    base         = os.path.dirname(os.path.abspath(__file__))
    detail_path  = args.output_detail  or os.path.join(base, f"detail_{tag}.csv")
    summary_path = args.output_summary or os.path.join(base, f"summary_{tag}.csv")

    files = glob.glob(args.data, recursive=True)
    print(f"Found {len(files)} stock files.")

    all_detail  = []
    all_summary = []
    failed = completed = 0
    max_workers = min(32, (os.cpu_count() or 1) * 4)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_file, f, args.years, args.multiple, args.yoy_threshold): f
            for f in files
        }
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            try:
                detail_rows, summary_row = future.result()
                all_detail.extend(detail_rows)
                if summary_row:
                    all_summary.append(summary_row)
            except Exception as exc:
                failed += 1
                print(f"  ERROR {futures[future]}: {exc}")

            if completed % args.progress == 0:
                print(f"  Progress: {completed}/{len(files)} files done ...")

    print(f"\nDone. Processed: {completed}, Failed: {failed}")
    print(f"Qualified stocks:   {len(all_summary)}")
    print(f"Total detail rows:  {len(all_detail)}")

    if all_detail:
        df_detail = pd.DataFrame(all_detail)
        df_detail = df_detail.sort_values("qualified_start_date").reset_index(drop=True)
        df_detail.to_csv(detail_path, index=False)
        print(f"Detail  -> {detail_path}")

    if all_summary:
        df_summary = pd.DataFrame(all_summary)
        df_summary = df_summary.sort_values("qualified_start_date").reset_index(drop=True)
        df_summary.to_csv(summary_path, index=False)
        print(f"Summary -> {summary_path}")


if __name__ == "__main__":
    main()

# example usage:
# python fast.py --years 3 --multiple 10 --yoy_threshold 30
# python fast.py --years 5 --multiple 30 --yoy_threshold 25
# example usage:
# python fast.py --years 3 --multiple 10 --yoy_threshold 30
# python fast.py --years 5 --multiple 30 --yoy_threshold 25
# python fast.py --years 10 --multiple 100 --yoy_threshold 20