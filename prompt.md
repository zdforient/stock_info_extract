data stucture:
<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>
AADR.US,D,20100721,000000,23.1646,23.1646,22.7969,22.7969,45503.680330826,0
AADR.US,D,20100722,000000,23.4621,23.4621,23.1929,23.3129,18940.045746928,0
AADR.US,D,20100723,000000,23.5713,23.5713,23.1471,23.3324,9345.9703923893,0
AADR.US,D,20100726,000000,23.4426,23.4426,23.2768,23.4153,20422.52415713,0
AADR.US,D,20100727,000000,23.3031,23.3411,23.2603,23.3411,8882.5677358118,0
paths: /Users/df/Documents/stock/history/daily/us/*/*.txt

stock name is in aadr.us.txt before the .us.txt

I want the list of stocks that increased for more than 20 times in 3 years in the database. 

sort the output by start time

Modify my Python script to scan stock history files with multithreading.

Data path:

/Users/df/Documents/stock/history/daily/us/*/*.txt

Each file has columns:

<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>

Ticker name rule:

Example file: aadr.us.txt
stock_name = AADR

Goal:

Find all stocks that increased more than 20x within any rolling 3-year period.

Use CLOSE price.

For every start date, find the first trading day on or after start_date + 3 calendar years.

growth_multiple = end_close / start_close

If growth_multiple >= 20, record it.

Output fields:

stock_name
time_start
time_end
start_price
end_price
growth_multiple

Sort final output by time_start ascending.

Save result to:

three_year_20x_stocks.csv

Implementation requirements:

1. Use glob to find all txt files.
2. Use concurrent.futures.ThreadPoolExecutor for multithreading.
3. Use max_workers = min(32, os.cpu_count() * 4).
4. Each worker processes one file independently.
5. Read each file with pandas.
6. Parse DATE as datetime using format "%Y%m%d".
7. Convert CLOSE to numeric.
8. Drop rows where DATE is invalid, CLOSE is missing, or CLOSE <= 0.
9. Sort by DATE.
10. Use numpy.searchsorted to find the first trading day on or after start_date + 3 years.
11. Avoid nested O(n^2) logic.
12. If multiple qualifying windows exist for one stock, keep all qualifying windows.
13. Collect results from all futures safely in the main thread.
14. Print progress every 500 completed files.
15. Catch exceptions per file and continue processing.
16. At the end, sort by time_start ascending and export CSV.
17. Print total files processed, total failed files, and total qualifying windows.

Write clean complete Python code.

For each stock, once a qualifying 3-year 20x window is found:

record this row

then skip all start dates before that row's end_date

continue scanning from the first trading date after or equal to end_date