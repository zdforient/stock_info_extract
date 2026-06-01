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
    results = []

    df = pd.read_csv(filepath, header=0)
    df.columns = [c.strip().strip("<>") for c in df.columns]
    df["DATE"] = pd.to_datetime(df["DATE"], format="%Y%m%d", errors="coerce")
    df["CLOSE"] = pd.to_numeric(df["CLOSE"], errors="coerce")
    df = df.dropna(subset=["DATE", "CLOSE"])
    df = df[df["CLOSE"] > 0]
    if len(df) < 2:
        return results

    df = df.sort_values("DATE").reset_index(drop=True)
    closes = df["CLOSE"].values
    dates_ord = df["DATE"].values.astype("datetime64[D]").astype(np.int64)
    n = len(df)

    scan_i = 0  # where to resume searching for the next qualifying window

    while True:
        # ---------------------------------------------------------- #
        # STEP 1: Find earliest qualifying window from scan_i onward  #
        #   For each buy-date t, look at every trading day in         #
        #   [t + 1 year, t + X years].  Qualify on the FIRST day     #
        #   the price reaches multiple × buy_price.                   #
        # ---------------------------------------------------------- #
        qual_i = qual_j = -1
        for i in range(scan_i, n):
            j_min = find_idx(dates_ord, df["DATE"].iat[i] + relativedelta(years=1))
            if j_min == -1:
                break  # no data 1 year ahead

            cutoff_ord = ts_to_ord(df["DATE"].iat[i] + relativedelta(years=years))
            j_max = int(np.searchsorted(dates_ord, cutoff_ord, side="right")) - 1

            if j_max < j_min:
                continue

            hits = np.where(closes[j_min : j_max + 1] >= closes[i] * multiple)[0]
            if len(hits) > 0:
                qual_i = i
                qual_j = j_min + int(hits[0])
                break

        if qual_i == -1:
            break  # no more qualifying windows in this file

        q_start_ts    = df["DATE"].iat[qual_i]
        q_start_price = closes[qual_i]

        # ---------------------------------------------------------- #
        # STEP 2: Walk forward year by year from qual_j (the X-year  #
        #         mark). end_date = last year-end with YoY >= Z%.    #
        #         If year 1 from qual_j already fails, end = qual_j  #
        # ---------------------------------------------------------- #
        prev_idx = qual_j
        end_idx  = qual_j   # default: the X-year qualification mark

        for _ in range(1, 100_000):
            j = find_idx(dates_ord, df["DATE"].iat[prev_idx] + relativedelta(years=1))
            if j == -1:
                break
            yoy_pct = (closes[j] / closes[prev_idx] - 1) * 100
            if yoy_pct < yoy_threshold:
                break
            end_idx  = j
            prev_idx = j

        end_ts    = df["DATE"].iat[end_idx]
        end_price = closes[end_idx]
        duration  = round((end_ts - q_start_ts).days / 365.25, 2)

        results.append({
            "stock_name":      stock_name,
            "start_date":      q_start_ts.strftime("%Y-%m-%d"),
            "end_date":        end_ts.strftime("%Y-%m-%d"),
            "start_price":     round(q_start_price, 6),
            "end_price":       round(end_price, 6),
            "total_multiple":  round(end_price / q_start_price, 4),
            "duration_years":  duration,
        })

        # Resume search for the next episode after end_date
        scan_i = end_idx

    return results


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
    parser.add_argument("--output", default=None,
                        help="Output CSV path (auto-named if omitted)")
    parser.add_argument("--progress", type=int, default=500,
                        help="Print progress every N files (default: 500)")
    parser.add_argument("--debug", action="store_true",
                        help="Print the first 10 qualifying results and exit without saving")
    args = parser.parse_args()

    tag         = f"{args.years}yr_{int(args.multiple)}x_{int(args.yoy_threshold)}pct"
    base        = os.path.dirname(os.path.abspath(__file__))
    output_path = args.output or os.path.join(base, f"results_{tag}.csv")

    files = glob.glob(args.data, recursive=True)
    print(f"Found {len(files)} stock files.")

    all_results = []
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
                all_results.extend(future.result())
            except Exception as exc:
                failed += 1
                print(f"  ERROR {futures[future]}: {exc}")

            if args.debug and len(all_results) >= 10:
                for f in futures:
                    f.cancel()
                break

            if completed % args.progress == 0:
                print(f"  Progress: {completed}/{len(files)} files done ...")

    print(f"\nDone. Processed: {completed}, Failed: {failed}")
    print(f"Total qualifying episodes: {len(all_results)}")

    if not all_results:
        print("No qualifying stocks found.")
        return

    if args.debug:
        debug_path = output_path.replace(".csv", "_debug.csv")
        df_out = pd.DataFrame(all_results).sort_values("start_date").head(10)
        df_out.to_csv(debug_path, index=False)
        print(f"Debug  -> {debug_path}")
        print(df_out.to_string(index=False))
        return

    df_out = pd.DataFrame(all_results)
    df_out = df_out.sort_values("start_date").reset_index(drop=True)
    df_out.to_csv(output_path, index=False)
    print(f"Results -> {output_path}")


if __name__ == "__main__":
    main()

# example usage:
# python fast.py --years 3 --multiple 10 --yoy_threshold 30
# python fast.py --years 5 --multiple 30 --yoy_threshold 25
# python fast.py --years 10 --multiple 100 --yoy_threshold 20