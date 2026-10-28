"""Streamlit interface. Run with:  streamlit run app.py"""
import datetime
import os
from collections import Counter

import streamlit as st

from core.analysis import analyze, line_members
from core.authors import author_teams
from core.mock import mock_corpus
from core.openalex import OpenAlexClient, assign_roles, build_corpus, expand_corpus
from core.plot import draw_line_graph

THIS_YEAR = datetime.date.today().year
st.set_page_config(page_title="Research line explorer", layout="wide")
st.title("Research line explorer")
st.caption("Seed papers from a keyword search, expanded to their citation neighbourhood, "
           "then explored as a directed, weighted graph.")


def shared_key():
    """Key from the server's secrets or environment. Never placed in a widget, so visitors cannot read it."""
    try:
        if "OPENALEX_API_KEY" in st.secrets:
            return st.secrets["OPENALEX_API_KEY"]
    except Exception:  # no secrets file configured
        pass
    return os.environ.get("OPENALEX_API_KEY", "")


@st.cache_resource
def get_client(api_key):
    return OpenAlexClient(api_key or None)


@st.cache_resource(show_spinner="Building graph and clustering...", max_entries=3)
def run(_works, fingerprint, min_cocitations, resolution, min_size, exclude_reviews):
    return analyze(_works, min_cocitations=min_cocitations, resolution=resolution,
                   min_size=min_size, exclude_reviews=exclude_reviews)


# ---------------------------------------------------------------- sidebar: seed papers
with st.sidebar:
    st.header("1. Seed papers")
    use_mock = st.checkbox("Use mock data (no API calls)")
    query = st.text_input("Keywords", "CRISPR base editing")
    year_from, year_to = st.slider("Publication years", 1990, THIS_YEAR, (2012, THIS_YEAR))
    min_citations = st.number_input("Minimum citations", 0, 10_000, 5)
    types = st.multiselect("Work types", ["article", "review", "preprint"], default=["article", "review"])
    n_seeds = st.number_input("Number of seed papers (most relevant)", 20, 1000, 200, step=10)
    typed_key = st.text_input("OpenAlex API key (optional)", type="password",
                              help="Free at openalex.org/settings/api. Leave blank to use the app's default.")
    api_key = typed_key or shared_key()
    if not typed_key and shared_key():
        st.caption("Using the app's shared API key.")
    filters = dict(year_from=year_from, year_to=year_to, min_citations=min_citations, types=types)

    c1, c2 = st.columns(2)
    do_count = c1.button("Check count")
    do_seeds = c2.button("Fetch seeds", type="primary")

    if do_count and not use_mock:
        try:
            st.info(f"{get_client(api_key).count(query, **filters):,} works match; "
                    f"the {int(n_seeds)} most relevant become seeds.")
        except Exception as e:
            st.error(str(e))

    if do_seeds:
        try:
            if use_mock:
                n = min(int(n_seeds), 60)
                seeds = mock_corpus(n_seeds=n, expand=False)
                full = mock_corpus(n_seeds=n, expand=True)
                st.session_state["citing_estimate"] = sum(w["role"] in ("citing", "both") for w in full)
            else:
                client = get_client(api_key)
                bar = st.progress(0.0, text="Fetching seed papers...")
                seeds = build_corpus(client, query, n_seeds=int(n_seeds), expand=False,
                                     progress=lambda label, d, t: bar.progress(min(d / max(t, 1), 1.0)), **filters)
                bar.empty()
                st.session_state["citing_estimate"] = client.count_citing({w["id"] for w in seeds})
            st.session_state.update(seeds=seeds, works=seeds, query="mock data" if use_mock else query,
                                    mock=use_mock)
        except Exception as e:
            st.error(str(e))

seeds = st.session_state.get("seeds")
if not seeds:
    st.info("Enter keywords in the sidebar, check the count, then press Fetch seeds. "
            "Tick 'Use mock data' to try the interface without network access.")
    st.stop()

# ---------------------------------------------------------------- 2. first neighbours
st.subheader(f"2. First neighbours of the seeds: {st.session_state['query']}")
seed_ids = {w["id"] for w in seeds}
n_cited = len({r for w in seeds for r in w["refs"]} - seed_ids)
m1, m2, m3 = st.columns(3)
m1.metric("Seed papers", f"{len(seeds):,}")
m2.metric("Cited by seeds (to fetch)", f"{n_cited:,}")
m3.metric("Citing seeds (upper estimate)", f"{st.session_state.get('citing_estimate', 0):,}")
max_citing = st.number_input("Max citing papers to fetch", 100, 200_000, 10_000, step=1000,
                             help="Fetching every citing paper can be large. When the cap bites, the most-cited "
                                  "citing papers are kept first. Bigger corpora make the graph step slower.")
if st.button("Fetch first neighbours"):
    try:
        if st.session_state["mock"]:
            st.session_state["works"] = mock_corpus(n_seeds=len(seeds), expand=True)
        else:
            bar = st.progress(0.0)
            st.session_state["works"] = expand_corpus(
                get_client(api_key), seeds, int(max_citing),
                progress=lambda label, d, t: bar.progress(min(d / max(t, 1), 1.0), text=f"{label} ({d}/{t})"))
            bar.empty()
    except Exception as e:
        st.error(str(e))

works = st.session_state["works"]
roles = Counter(w["role"] for w in works)
if len(works) > len(seeds):
    st.success(f"Corpus: {len(works):,} papers ({roles['seed']} seeds, {roles['cited']} cited, "
               f"{roles['citing']} citing, {roles['both']} both).")
else:
    st.warning("Currently using the seed papers only. Fetch first neighbours to build the full graph.")

# ---------------------------------------------------------------- 3. tune the map
st.subheader("3. Graph and research lines")
st.caption("Clustering is a placeholder (Louvain on the undirected weights); see core/clustering.py.")
k1, k2, k3 = st.columns(3)
min_cocitations = k1.slider("Min co-citations", 1, 10, 2,
                            help="A pair of papers must be cited together at least this often to get a "
                                 "co-citation weight. Direct citations always count.")
resolution = k2.slider("Resolution", 0.2, 3.0, 1.0, 0.1, help="Higher = more, smaller research lines")
min_size = k3.slider("Min cluster size", 2, 100, 10)
exclude_reviews = st.checkbox("Exclude reviews when clustering (shown separately as entry points)", True)

fingerprint = f"{len(works)}-{works[0]['id']}-{works[-1]['id']}"
res = run(works, fingerprint, min_cocitations, resolution, min_size, exclude_reviews)

s = res.stats
st.write(f"**{s['clusters']} research lines** covering {s['clustered']:,} of {s['works']:,} papers "
         f"({s['unclustered']:,} unclustered). Graph: {s['edges']:,} edges "
         f"({s['citation_edges']:,} direct citations, {s['cocitation_only_edges']:,} co-cited only).")
if res.summary.empty:
    st.warning("No clusters found. Lower 'Min cluster size' or 'Min co-citations', or fetch more papers.")
    st.stop()
st.dataframe(res.summary, hide_index=True)

# ---------------------------------------------------------------- 4. inspect one line
st.subheader("4. Inspect a research line")
labels = dict(zip(res.summary.cluster, res.summary.label))
cid = st.selectbox("Research line", list(labels), format_func=lambda c: f"{c}: {labels[c]}")
d = res.detail[cid]
members = line_members(res, cid)
cols = ["year", "title", "in_cluster_cites", "cited_by", "cites_per_year", "role", "url"]

t1, t2, t3, t4 = st.tabs(["Key papers", "Reviews (entry points)", "Graph", "Authors and timeline"])
with t1:
    st.caption("Ranked by citations from other papers in the same line. Sort by year for a reading path.")
    st.dataframe(d["papers"][cols], hide_index=True)
with t2:
    if d["reviews"].empty:
        st.write("No reviews attached to this line. Add 'review' to the work types and fetch again.")
    else:
        st.dataframe(d["reviews"][cols], hide_index=True)
with t3:
    g1, g2, g3 = st.columns(3)
    layout = g1.radio("Layout", ["force", "timeline"], horizontal=True,
                      format_func=lambda x: "Force-directed" if x == "force" else "Timeline (x = year)")
    max_nodes = g2.slider("Max papers drawn", 20, 300, 100, 10,
                          help="If the line is larger, the best-connected papers are drawn.")
    n_labels = g3.slider("Labelled papers", 0, 25, 8)
    st.pyplot(draw_line_graph(res.graph, res.by_id, members, layout=layout,
                              max_nodes=max_nodes, n_labels=n_labels))
    st.caption("Arrows run from the cited to the citing paper. Dashed orange lines join papers that are "
               "co-cited but do not cite each other (oriented old to new). Node size = citations received "
               "within the drawing; colour = publication year; black ring = seed paper.")
with t4:
    a1, a2, a3 = st.columns(3)
    min_support = a1.slider("Min papers together", 2, 20, 3)
    max_group = a2.slider("Max group size", 2, 6, 4)
    closed_only = a3.checkbox("Closed groups only", True,
                              help="Hide a group when a larger group appears in exactly the same papers.")
    left, right = st.columns(2)
    left.write("Frequently co-occurring authors (frequent itemsets; each paper is a basket of authors)")
    teams = author_teams([res.by_id[i] for i in members], min_support=min_support,
                         max_size=max_group, closed_only=closed_only)
    if teams.empty:
        left.write("No author group reaches this support. Lower 'Min papers together'.")
    else:
        left.dataframe(teams, hide_index=True)
    left.caption("Papers with more than 25 authors are ignored. Authors are matched by OpenAlex author id.")
    right.write("Papers per year")
    right.bar_chart(d["years"])

st.download_button("Download all papers with clusters (CSV)", res.papers.to_csv(index=False),
                   "papers_with_clusters.csv", "text/csv")
