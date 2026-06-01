import argparse
import glob
import os
import concurrent.futures
from datetime import timedelta

import numpy as np
import pandas as pd


def extract_stock_name(filepath: str) -> str:
    """Return uppercase ticker from filename, e.g. aadr.us.txt -> AADR."""
    basename = os.path.basename(filepath)          # aadr.us.txt
    name = basename.split(".")[0]                  # aadr
    return name.upper()                            # AADR


def process_file(filepath: str, growth_threshold: float, window_days: int) -> list[dict]:
    """
    Scan one stock file for qualifying windows with >= growth_threshold growth.
    Returns a list of qualifying result dicts.
    """
    stock_name = extract_stock_name(filepath)
    results = []

    df = pd.read_csv(filepath, header=0)

    # Normalise column names (strip whitespace/angle brackets)
    df.columns = [c.strip().strip("<>") for c in df.columns]

    # Parse DATE and CLOSE
    df["DATE"] = pd.to_datetime(df["DATE"], format="%Y%m%d", errors="coerce")
    df["CLOSE"] = pd.to_numeric(df["CLOSE"], errors="coerce")

    # Drop invalid rows
    df = df.dropna(subset=["DATE", "CLOSE"])
    df = df[df["CLOSE"] > 0]

    if len(df) < 2:
        return results

    df = df.sort_values("DATE").reset_index(drop=True)

    dates = df["DATE"].values          # numpy datetime64 array
    closes = df["CLOSE"].values        # numpy float array

    # Convert dates to ordinal integers for searchsorted
    dates_ord = dates.astype("datetime64[D]").astype(np.int64)

    n = len(df)
    i = 0
    while i < n:
        start_date_ord = dates_ord[i]
        target_ord = start_date_ord + window_days

        # First trading day on or after start_date + window
        j = int(np.searchsorted(dates_ord, target_ord, side="left"))
        if j >= n:
            break

        start_close = closes[i]
        end_close = closes[j]
        growth = end_close / start_close

        if growth >= growth_threshold:
            results.append({
                "stock_name": stock_name,
                "time_start": df["DATE"].iat[i].strftime("%Y-%m-%d"),
                "time_end": df["DATE"].iat[j].strftime("%Y-%m-%d"),
                "start_price": round(start_close, 6),
                "end_price": round(end_close, 6),
                "growth_multiple": round(growth, 4),
            })
            # Jump: next start is the first trading day >= end_date
            i = j
        else:
            i += 1

    return results


def main():
    parser = argparse.ArgumentParser(description="Find stocks with 20x+ growth in a rolling window.")
    parser.add_argument("--data", default="/Users/df/Documents/stock/history/daily/us/**/*.txt",
                        help="Glob pattern for stock .txt files")
    parser.add_argument("--output", default="/Users/df/Documents/stock/history/three_year_20x_stocks.csv",
                        help="Output CSV path")
    parser.add_argument("--growth", type=float, default=20.0,
                        help="Minimum growth multiple (default: 20.0)")
    parser.add_argument("--window", type=int, default=365 * 3,
                        help="Window size in days (default: 1095 = 3 years)")
    parser.add_argument("--progress", type=int, default=500,
                        help="Print progress every N files (default: 500)")
    args = parser.parse_args()

    files = glob.glob(args.data, recursive=True)
    total_files = len(files)
    print(f"Found {total_files} stock files.")

    all_results = []
    failed = 0
    completed = 0

    max_workers = min(32, (os.cpu_count() or 1) * 4)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(process_file, f, args.growth, args.window): f
            for f in files
        }

        for future in concurrent.futures.as_completed(future_to_file):
            completed += 1
            try:
                result = future.result()
                all_results.extend(result)
            except Exception as exc:
                failed += 1
                fp = future_to_file[future]
                print(f"  ERROR processing {fp}: {exc}")

            if completed % args.progress == 0:
                print(f"  Progress: {completed}/{total_files} files done ...")

    print(f"\nDone. Total files processed: {completed}, failed: {failed}")
    print(f"Total qualifying 20x windows: {len(all_results)}")

    if not all_results:
        print("No qualifying stocks found.")
        return

    df_out = pd.DataFrame(all_results)
    df_out = df_out.sort_values("time_start").reset_index(drop=True)
    df_out.to_csv(args.output, index=False)
    print(f"Results saved to: {args.output}")


if __name__ == "__main__":
    main()

#example usage:
# python get_info.py