"""Command-line runner: python cli.py --mock   |   python cli.py --query "CRISPR base editing" --from 2015"""
import argparse

import pandas as pd

from core.analysis import analyze
from core.mock import mock_works
from core.openalex import OpenAlexClient, normalize_all

p = argparse.ArgumentParser()
p.add_argument("--query", default="CRISPR base editing")
p.add_argument("--from", dest="year_from", type=int, default=2012)
p.add_argument("--to", dest="year_to", type=int, default=None)
p.add_argument("--min-citations", type=int, default=5)
p.add_argument("--max", dest="max_results", type=int, default=2000)
p.add_argument("--types", default="article,review")
p.add_argument("--count-only", action="store_true", help="only show how many works match")
p.add_argument("--mock", action="store_true", help="use synthetic data, no network")
p.add_argument("--mode", default="both", choices=["citation", "cocitation", "both"])
p.add_argument("--min-cocitations", type=int, default=2)
p.add_argument("--resolution", type=float, default=1.0)
p.add_argument("--min-size", type=int, default=10)
a = p.parse_args()

if a.mock:
    works = mock_works()
else:
    client = OpenAlexClient()
    filt = dict(year_from=a.year_from, year_to=a.year_to, min_citations=a.min_citations,
                types=a.types.split(","))
    n = client.count(a.query, **filt)
    print(f"{n:,} works match your query.")
    if a.count_only:
        raise SystemExit
    raw = client.fetch(a.query, max_results=a.max_results,
                       progress=lambda d, t: print(f"  fetched {d}/{t}", end="\r"), **filt)
    works = normalize_all(raw)
    print(f"\nFetched {len(works)} works.")

res = analyze(works, a.mode, a.min_cocitations, a.resolution, a.min_size)
print("\n", res.stats)
pd.set_option("display.width", 200, "display.max_colwidth", 60)
print(res.summary.to_string(index=False))
for c, d in res.detail.items():
    print(f"\n=== Line {c}: {res.summary.set_index('cluster').loc[c, 'label']} ===")
    print(d["papers"].head(5)[["year", "title", "in_cluster_cites", "cited_by"]].to_string(index=False))
