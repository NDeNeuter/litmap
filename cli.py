"""Command-line runner.
  python cli.py --mock
  python cli.py --query "CRISPR base editing" --count-only
  python cli.py --query "CRISPR base editing" --seeds 200 --graph-line 1
"""
import argparse
from collections import Counter

import pandas as pd

from core.analysis import analyze, line_members
from core.authors import author_teams
from core.mock import mock_corpus
from core.openalex import OpenAlexClient, build_corpus
from core.plot import draw_line_graph

p = argparse.ArgumentParser()
p.add_argument("--query", default="CRISPR base editing")
p.add_argument("--from", dest="year_from", type=int, default=2012)
p.add_argument("--to", dest="year_to", type=int, default=None)
p.add_argument("--min-citations", type=int, default=5)
p.add_argument("--types", default="article,review")
p.add_argument("--seeds", type=int, default=200, help="number of most relevant papers to start from")
p.add_argument("--no-expand", action="store_true", help="skip the first-neighbour pass")
p.add_argument("--max-citing", type=int, default=10000, help="cap on citing papers fetched")
p.add_argument("--count-only", action="store_true", help="only show how many works match")
p.add_argument("--mock", action="store_true", help="use synthetic data, no network")
p.add_argument("--min-cocitations", type=int, default=2)
p.add_argument("--resolution", type=float, default=1.0)
p.add_argument("--min-size", type=int, default=10)
p.add_argument("--graph-line", type=int, help="save the graph of this research line as line_N.png")
a = p.parse_args()

if a.mock:
    works = mock_corpus(n_seeds=min(a.seeds, 60), expand=not a.no_expand)
else:
    client = OpenAlexClient()
    filt = dict(year_from=a.year_from, year_to=a.year_to, min_citations=a.min_citations,
                types=a.types.split(","))
    print(f"{client.count(a.query, **filt):,} works match your query (the {a.seeds} most relevant are used as seeds).")
    if a.count_only:
        raise SystemExit
    works = build_corpus(client, a.query, n_seeds=a.seeds, expand=not a.no_expand, max_citing=a.max_citing,
                         progress=lambda label, d, t: print(f"  {label}: {d}/{t}      ", end="\r"), **filt)
    print()

print("Corpus:", len(works), "papers", dict(Counter(w["role"] for w in works)))
res = analyze(works, min_cocitations=a.min_cocitations, resolution=a.resolution, min_size=a.min_size)
print(res.stats)
pd.set_option("display.width", 200, "display.max_colwidth", 60)
print(res.summary.to_string(index=False))

for c, d in res.detail.items():
    print(f"\n=== Line {c}: {res.summary.set_index('cluster').loc[c, 'label']} ===")
    print(d["papers"].head(5)[["year", "title", "in_cluster_cites", "cited_by"]].to_string(index=False))
    teams = author_teams([res.by_id[i] for i in line_members(res, c)]).head(3)
    if not teams.empty:
        print("Frequent author groups:")
        print(teams.to_string(index=False))

if a.graph_line:
    fig = draw_line_graph(res.graph, res.by_id, line_members(res, a.graph_line))
    fig.savefig(f"line_{a.graph_line}.png")
    print(f"\nSaved line_{a.graph_line}.png")
