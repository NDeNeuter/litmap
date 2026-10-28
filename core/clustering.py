"""PLACEHOLDER clustering of the directed, weighted citation graph.

Swap `cluster_lines` for your own method. The contract is small: take the graph from
analysis.build_graph and return {paper_id: line_number}, numbering lines from 1 (largest first)
and leaving unclustered papers out of the dict.
"""
from collections import Counter

import networkx as nx


def cluster_lines(D, by_id, resolution=1.0, min_size=10, exclude_reviews=True, seed=42):
    """Louvain on the undirected projection (edge weights summed over both directions).

    Reviews cite broadly and tie unrelated lines together, so by default they are left out of
    the clustering and then attached to the line holding most of the papers they cite.
    """
    skip = {i for i, w in by_id.items() if exclude_reviews and w["type"] == "review"}
    U = nx.Graph()
    for u, v, d in D.edges(data=True):
        if u in skip or v in skip:
            continue
        if U.has_edge(u, v):
            U[u][v]["weight"] += d["weight"]
        else:
            U.add_edge(u, v, weight=d["weight"])
    if U.number_of_edges() == 0:
        return {}

    comms = nx.community.louvain_communities(U, weight="weight", resolution=resolution, seed=seed)
    membership, k = {}, 0
    for comm in sorted(comms, key=len, reverse=True):
        if len(comm) >= min_size:
            k += 1
            membership.update({n: k for n in comm})

    for rid in skip:  # edge u -> rid with citation=1 means rid cites u
        refs = [u for u, _, d in D.in_edges(rid, data=True) if d["citation"]]
        votes = Counter(membership[r] for r in refs if r in membership)
        if votes:
            membership[rid] = votes.most_common(1)[0][0]
    return membership
