"""Frequent co-authorship groups via frequent itemset mining (each paper is a basket of authors)."""
from collections import Counter, defaultdict
from itertools import combinations

import pandas as pd


def frequent_itemsets(baskets, min_support=3, max_size=4, max_basket=25):
    """Apriori. Returns {frozenset(items): number of baskets containing all of them}.

    Baskets larger than max_basket (consortium papers) are ignored: they would generate
    enormous numbers of meaningless combinations.
    """
    baskets = [frozenset(b) for b in baskets if 0 < len(b) <= max_basket]
    counts = Counter(i for b in baskets for i in b)
    level = {frozenset([i]): c for i, c in counts.items() if c >= min_support}
    result = dict(level)
    keep = {i for s in level for i in s}
    baskets = [b & keep for b in baskets]

    k = 2
    while level and k <= max_size:
        prev = set(level)
        candidates = set()
        for a, b in combinations(prev, 2):
            u = a | b
            if len(u) == k and all(frozenset(s) in prev for s in combinations(u, k - 1)):
                candidates.add(u)
        if not candidates:
            break
        counts = Counter()
        for b in baskets:
            if len(b) >= k:
                for combo in combinations(sorted(b), k):
                    fs = frozenset(combo)
                    if fs in candidates:
                        counts[fs] += 1
        level = {s: c for s, c in counts.items() if c >= min_support}
        result.update(level)
        k += 1
    return result


def author_teams(works, min_support=3, max_size=4, min_size=2, max_authors=25, closed_only=True):
    """Groups of authors who repeatedly publish together within a set of papers.

    closed_only drops a group when a larger group appears in exactly the same papers, which
    removes redundant sub-groups.
    """
    names = defaultdict(Counter)
    baskets = []
    for w in works:
        keys = set()
        for a in w["authors"]:
            key = a["id"] or a["name"]
            if key:
                names[key][a["name"] or key] += 1
                keys.add(key)
        baskets.append(keys)

    sets = frequent_itemsets(baskets, min_support, max_size, max_authors)
    if closed_only:
        by_count = defaultdict(list)
        for s, c in sets.items():
            by_count[c].append(s)
        sets = {s: c for s, c in sets.items() if not any(s < t for t in by_count[c])}

    rows = [{"authors": "; ".join(sorted(names[k].most_common(1)[0][0] for k in s)),
             "size": len(s), "papers": c, "share_of_line": f"{100 * c / max(1, len(works)):.0f}%"}
            for s, c in sets.items() if len(s) >= min_size]
    cols = ["authors", "size", "papers", "share_of_line"]
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values(["papers", "size"], ascending=False).reset_index(drop=True)
