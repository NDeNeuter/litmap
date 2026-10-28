"""Draw the graph behind one research line (matplotlib, no pyplot state)."""
import math

import networkx as nx
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

CITE_COLOR, COCITE_COLOR = "#666666", "#E08A1E"


def _label(w):
    first = (w["authors"][0]["name"] or "") if w["authors"] else ""
    surname = first.split()[-1] if first else w["id"]
    return f"{surname} {w['year']}"


def draw_line_graph(D, by_id, members, layout="force", max_nodes=120, n_labels=8):
    """Subgraph of one line. Arrows run cited -> citing; dashed lines are co-cited-only pairs.
    Node size = citations received inside the drawing, colour = year, black ring = seed paper."""
    sub = D.subgraph([n for n in members if n in D])
    if sub.number_of_nodes() > max_nodes:
        deg = dict(sub.degree(weight="weight"))
        sub = sub.subgraph(sorted(deg, key=deg.get, reverse=True)[:max_nodes])
    sub = sub.copy()
    nodes = list(sub.nodes)

    U = nx.Graph()
    U.add_nodes_from(nodes)
    for u, v, d in sub.edges(data=True):
        U.add_edge(u, v, weight=1 + math.log(d["weight"]))
    pos = nx.spring_layout(U, weight="weight", seed=1)
    if layout == "timeline":  # x = publication year, y = position from the force layout
        pos = {n: (by_id[n]["year"] + 0.35 * pos[n][0], pos[n][1]) for n in nodes}

    received = {n: sum(d["citation"] for *_, d in sub.out_edges(n, data=True)) for n in nodes}
    sizes = [30 + 22 * math.sqrt(received[n]) for n in nodes]
    years = [by_id[n]["year"] for n in nodes]
    direct = [(u, v) for u, v, d in sub.edges(data=True) if d["citation"]]
    cocit = [(u, v) for u, v, d in sub.edges(data=True) if not d["citation"]]

    m = len(direct) + len(cocit)  # denser graphs get fainter, smaller edges
    alpha = 0.55 if m < 100 else 0.35 if m < 400 else 0.2
    head = 7 if m < 100 else 5
    fig = Figure(figsize=(9, 6), dpi=110)
    ax = fig.subplots()
    if cocit:
        nx.draw_networkx_edges(sub, pos, edgelist=cocit, ax=ax, arrows=False, style="dashed",
                               edge_color=COCITE_COLOR, alpha=min(alpha, 0.35),
                               width=[0.4 + 0.3 * math.log(sub[u][v]["weight"]) for u, v in cocit])
    if direct:
        nx.draw_networkx_edges(sub, pos, edgelist=direct, ax=ax, nodelist=nodes, node_size=sizes,
                               arrows=True, arrowstyle="-|>", arrowsize=head, edge_color=CITE_COLOR,
                               alpha=alpha, width=[0.5 + 0.3 * math.log(sub[u][v]["weight"]) for u, v in direct])
    coll = nx.draw_networkx_nodes(
        sub, pos, nodelist=nodes, node_size=sizes, node_color=years, cmap="viridis",
        vmin=min(years), vmax=max(years) if max(years) > min(years) else min(years) + 1, ax=ax,
        edgecolors=["black" if by_id[n].get("role") == "seed" else "white" for n in nodes],
        linewidths=[1.4 if by_id[n].get("role") == "seed" else 0.4 for n in nodes])
    top = sorted(nodes, key=lambda n: received[n], reverse=True)[:n_labels]
    nx.draw_networkx_labels(sub, pos, labels={n: _label(by_id[n]) for n in top}, font_size=7, ax=ax,
                            bbox=dict(facecolor="white", alpha=0.75, edgecolor="none", pad=0.6))

    fig.colorbar(coll, ax=ax, shrink=0.6, label="Publication year")
    ax.legend(handles=[
        Line2D([0], [0], color=CITE_COLOR, lw=1.2, label="Direct citation (cited \u2192 citing)"),
        Line2D([0], [0], color=COCITE_COLOR, lw=1.2, ls="--", label="Co-cited only"),
        Line2D([0], [0], marker="o", color="none", markeredgecolor="black", markerfacecolor="none",
               label="Seed paper")], loc="lower left", fontsize=7, frameon=False)
    if layout == "timeline":
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.set_yticks([])
        ax.tick_params(axis="x", bottom=True, labelbottom=True, labelsize=8)
    else:
        ax.set_axis_off()
    ax.margins(0.08)
    fig.tight_layout()
    return fig
