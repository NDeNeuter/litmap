"""Directed weighted citation graph, ranking and labeling. No UI and no network code."""
import datetime
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

import networkx as nx
import pandas as pd

from .clustering import cluster_lines

STOPWORDS = set("""a an and the of in on for to with by from at as is are was were be this that these those
using use based via into its their we our novel study analysis role new between during after about over under
through can may not no or than then also more most""".split())


@dataclass
class Result:
    summary: pd.DataFrame   # one row per research line
    detail: dict            # line -> {"papers", "reviews", "years"}
    papers: pd.DataFrame    # every paper with its line (0 = unclustered)
    stats: dict
    graph: nx.DiGraph       # the full directed weighted graph
    by_id: dict             # paper id -> normalized work
    membership: dict        # paper id -> line (clustered papers only)


def build_graph(works, min_cocitations=2, max_refs=100, count_review_cocitations=False):
    """Directed weighted graph over the corpus.

    Edge u -> v means "v cites u": influence flows from the cited paper to the citing one.
    Every edge carries
      citation   1 if v directly cites u, else 0
      cocitation number of corpus papers that cite both u and v (pairs seen fewer than
                 min_cocitations times are ignored)
      weight     citation + cocitation
    A co-cited pair without a direct citation has no natural direction, so the edge points from
    the older to the newer paper. Citing papers with more than max_refs in-corpus references are
    skipped for co-citation (they add noise and make pair counts explode). Reviews are skipped as
    co-citers unless count_review_cocitations is True.
    """
    by_id = {w["id"]: w for w in works}
    ids = sorted(by_id)
    idx = {i: n for n, i in enumerate(ids)}
    N = len(ids)

    D = nx.DiGraph()
    D.add_nodes_from(ids)
    for w in works:
        for r in w["refs"]:
            if r in idx and r != w["id"]:
                D.add_edge(r, w["id"], citation=1, cocitation=0)

    cocite = Counter()  # integer keys keep memory down on large corpora
    for w in works:
        if w["type"] == "review" and not count_review_cocitations:
            continue
        refs = sorted({idx[r] for r in w["refs"] if r in idx and r != w["id"]})
        if 2 <= len(refs) <= max_refs:
            for a, b in combinations(refs, 2):
                cocite[a * N + b] += 1

    for key, c in cocite.items():
        if c < min_cocitations:
            continue
        u, v = ids[key // N], ids[key % N]
        if D.has_edge(u, v):
            D[u][v]["cocitation"] += c
        elif D.has_edge(v, u):
            D[v][u]["cocitation"] += c
        else:
            if (by_id[u]["year"], u) > (by_id[v]["year"], v):
                u, v = v, u
            D.add_edge(u, v, citation=0, cocitation=c)

    for _, _, d in D.edges(data=True):
        d["weight"] = d["citation"] + d["cocitation"]
    return D


def _tokens(title):
    return [t for t in re.findall(r"[a-z][a-z0-9\-]{2,}", title.lower()) if t not in STOPWORDS]


def label_clusters(titles_by_cluster, top=4):
    """Keywords frequent in one line but rare in the others (TF-IDF style)."""
    tf = {c: Counter(tok for t in titles for tok in _tokens(t)) for c, titles in titles_by_cluster.items()}
    df = Counter(tok for cnt in tf.values() for tok in cnt)
    n = len(tf)
    labels = {}
    for c, cnt in tf.items():
        scored = sorted(cnt, key=lambda tok: cnt[tok] * math.log((1 + n) / (1 + df[tok])) + 1e-6 * cnt[tok],
                        reverse=True)
        labels[c] = ", ".join(scored[:top])
    return labels


def line_members(res, line):
    return [i for i, c in res.membership.items() if c == line]


def analyze(works, min_cocitations=2, max_refs=100, resolution=1.0, min_size=10,
            exclude_reviews=True, top_n=15, now_year=None):
    now_year = now_year or datetime.date.today().year
    by_id = {w["id"]: w for w in works}
    D = build_graph(works, min_cocitations, max_refs)
    full = cluster_lines(D, by_id, resolution, min_size, exclude_reviews)

    n_cite = sum(d["citation"] for *_, d in D.edges(data=True))
    stats = {"works": len(works), "edges": D.number_of_edges(), "citation_edges": n_cite,
             "cocitation_only_edges": D.number_of_edges() - n_cite,
             "clusters": len(set(full.values())), "clustered": len(full),
             "unclustered": len(works) - len(full)}

    rows = []
    for wid, w in by_id.items():
        c = full.get(wid, 0)
        rows.append({
            "id": wid, "title": w["title"], "year": w["year"], "type": w["type"], "role": w.get("role", ""),
            "cited_by": w["cited_by"],
            "cites_per_year": round(w["cited_by"] / max(1, now_year - w["year"] + 1), 1),
            "in_cluster_cites": sum(1 for _, v, d in D.out_edges(wid, data=True)
                                    if c and d["citation"] and full.get(v) == c),
            "cluster": c, "url": "https://openalex.org/" + wid})
    papers = pd.DataFrame(rows)
    if not full:
        return Result(pd.DataFrame(), {}, papers, stats, D, by_id, {})

    lines = sorted(set(full.values()))
    labels = label_clusters({c: papers.loc[papers.cluster == c, "title"].tolist() for c in lines})
    detail, summary_rows = {}, []
    for c in lines:
        members = papers[papers.cluster == c]
        arts = members[members.type != "review"].sort_values(["in_cluster_cites", "cited_by"], ascending=False)
        revs = members[members.type == "review"].sort_values("cited_by", ascending=False)
        topic = Counter(by_id[i]["topic"] for i in members.id if by_id[i]["topic"]).most_common(1)
        detail[c] = {"papers": arts.head(top_n), "reviews": revs.head(top_n),
                     "years": members.year.value_counts().sort_index()}
        summary_rows.append({
            "cluster": c, "label": labels[c], "n_papers": len(members), "n_reviews": len(revs),
            "year_min": int(members.year.min()), "year_median": int(statistics.median(members.year)),
            "year_max": int(members.year.max()), "top_topic": topic[0][0] if topic else ""})
    return Result(pd.DataFrame(summary_rows), detail, papers, stats, D, by_id, full)
