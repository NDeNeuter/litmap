"""Graph building, clustering, ranking and labeling. No UI and no network code."""
import datetime
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

import networkx as nx
import pandas as pd

STOPWORDS = set("""a an and the of in on for to with by from at as is are was were be this that these those
using use based via into its their we our novel study analysis role new between during after about over under
through can may not no or their than then also more most""".split())


@dataclass
class Result:
    summary: pd.DataFrame   # one row per research line
    detail: dict            # cluster id -> {"papers", "reviews", "authors", "years"}
    papers: pd.DataFrame    # every paper with its cluster (0 = unclustered)
    stats: dict


def citation_digraph(works):
    """Directed graph, edge u -> v means 'u cites v'. Only in-corpus papers."""
    ids = {w["id"] for w in works}
    D = nx.DiGraph()
    D.add_nodes_from(ids)
    for w in works:
        for r in w["refs"]:
            if r in ids and r != w["id"]:
                D.add_edge(w["id"], r)
    return D


def cluster_graph(D, by_id, mode="both", min_cocitations=2, exclude_reviews=True, max_refs=150):
    """Weighted undirected graph used for clustering.

    mode: 'citation' (direct links), 'cocitation' (cited together), or 'both'.
    min_cocitations: a co-citation pair must be cited together at least this often to count.
    Direct citations are always kept. In 'both' mode the edge weight is 1 per direct
    citation plus the co-citation count.
    Reviews cite broadly and glue unrelated lines together, so by default they are left out
    here and attached to a line afterwards (see assign_reviews).
    """
    skip = {i for i, w in by_id.items() if exclude_reviews and w["type"] == "review"}
    direct, cocite = Counter(), Counter()
    if mode in ("citation", "both"):
        for u, v in D.edges():
            if u not in skip and v not in skip:
                direct[tuple(sorted((u, v)))] += 1
    if mode in ("cocitation", "both"):
        for u in D.nodes():
            if u in skip:
                continue
            refs = sorted(v for v in D.successors(u) if v not in skip)
            if len(refs) > max_refs:  # very long reference lists add noise
                continue
            for pair in combinations(refs, 2):
                cocite[pair] += 1
    G = nx.Graph()
    for pair in set(direct) | set(cocite):
        co = cocite.get(pair, 0)
        co = co if co >= min_cocitations else 0
        weight = direct.get(pair, 0) + co
        if weight > 0:
            G.add_edge(*pair, weight=weight)
    return G


def detect(G, resolution=1.0, min_size=10, seed=42):
    """Louvain communities; clusters below min_size are left unclustered. Ids start at 1."""
    comms = nx.community.louvain_communities(G, weight="weight", resolution=resolution, seed=seed)
    membership, k = {}, 0
    for comm in sorted(comms, key=len, reverse=True):
        if len(comm) >= min_size:
            k += 1
            membership.update({n: k for n in comm})
    return membership


def assign_reviews(by_id, D, membership):
    """Attach each left-out review to the cluster it cites most."""
    out = {}
    for wid, w in by_id.items():
        if w["type"] == "review" and wid not in membership:
            c = Counter(membership[r] for r in D.successors(wid) if r in membership)
            if c:
                out[wid] = c.most_common(1)[0][0]
    return out


def _tokens(title):
    return [t for t in re.findall(r"[a-z][a-z0-9\-]{2,}", title.lower()) if t not in STOPWORDS]


def label_clusters(titles_by_cluster, top=4):
    """Keywords that are frequent in one cluster but rare in the others (TF-IDF style)."""
    tf = {c: Counter(tok for t in titles for tok in _tokens(t)) for c, titles in titles_by_cluster.items()}
    df = Counter(tok for cnt in tf.values() for tok in cnt)
    n = len(tf)
    labels = {}
    for c, cnt in tf.items():
        scored = sorted(cnt, key=lambda tok: cnt[tok] * math.log((1 + n) / (1 + df[tok])) + 1e-6 * cnt[tok],
                        reverse=True)
        labels[c] = ", ".join(scored[:top])
    return labels


def analyze(works, mode="both", min_cocitations=2, resolution=1.0, min_size=10,
            exclude_reviews=True, top_n=15, now_year=None):
    now_year = now_year or datetime.date.today().year
    by_id = {w["id"]: w for w in works}
    D = citation_digraph(works)
    G = cluster_graph(D, by_id, mode, min_cocitations, exclude_reviews)
    membership = detect(G, resolution, min_size) if G.number_of_edges() else {}
    full = {**assign_reviews(by_id, D, membership), **membership}

    stats = {"works": len(works), "edges": G.number_of_edges(), "clusters": len(set(full.values())),
             "clustered": len(full), "unclustered": len(works) - len(full)}

    rows = []
    for wid, w in by_id.items():
        c = full.get(wid, 0)
        rows.append({
            "id": wid, "title": w["title"], "year": w["year"], "type": w["type"],
            "cited_by": w["cited_by"],
            "cites_per_year": round(w["cited_by"] / max(1, now_year - w["year"] + 1), 1),
            "in_cluster_cites": sum(1 for u in D.predecessors(wid) if c and full.get(u) == c),
            "cluster": c, "url": "https://openalex.org/" + wid})
    papers = pd.DataFrame(rows)
    if not full:
        return Result(pd.DataFrame(), {}, papers, stats)

    labels = label_clusters({c: papers.loc[papers.cluster == c, "title"].tolist()
                             for c in sorted(set(full.values()))})
    detail, summary_rows = {}, []
    for c in sorted(set(full.values())):
        members = papers[papers.cluster == c]
        arts = members[members.type != "review"].sort_values(["in_cluster_cites", "cited_by"], ascending=False)
        revs = members[members.type == "review"].sort_values("cited_by", ascending=False)
        last_authors = Counter(a["name"] for i in members.id for a in by_id[i]["authors"]
                               if a["position"] == "last" and a["name"])
        authors = pd.DataFrame(last_authors.most_common(10), columns=["last_author", "papers"])
        topic = Counter(by_id[i]["topic"] for i in members.id if by_id[i]["topic"]).most_common(1)
        detail[c] = {"papers": arts.head(top_n), "reviews": revs.head(top_n), "authors": authors,
                     "years": members.year.value_counts().sort_index()}
        summary_rows.append({
            "cluster": c, "label": labels[c], "n_papers": len(members), "n_reviews": len(revs),
            "year_min": int(members.year.min()), "year_median": int(statistics.median(members.year)),
            "year_max": int(members.year.max()),
            "top_topic": topic[0][0] if topic else "",
            "top_authors": ", ".join(f"{r.last_author} ({r.papers})" for r in authors.head(3).itertuples())})
    return Result(pd.DataFrame(summary_rows), detail, papers, stats)
