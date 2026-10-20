"""Streamlit interface. Run with:  streamlit run app.py"""
import datetime
import os

import streamlit as st

from core.analysis import analyze
from core.mock import mock_works
from core.openalex import OpenAlexClient, normalize_all

THIS_YEAR = datetime.date.today().year
st.set_page_config(page_title="Research line explorer", layout="wide")
st.title("Research line explorer")
st.caption("Find the main established research lines in a field: query, fetch, then tune the cutoffs.")


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


@st.cache_data(show_spinner="Clustering...")
def run(_works, fingerprint, mode, min_cocitations, resolution, min_size, exclude_reviews):
    return analyze(_works, mode=mode, min_cocitations=min_cocitations, resolution=resolution,
                   min_size=min_size, exclude_reviews=exclude_reviews)


# ---------------------------------------------------------------- sidebar: define the field
with st.sidebar:
    st.header("1. Define the field")
    use_mock = st.checkbox("Use mock data (no API calls)")
    query = st.text_input("Keywords", "CRISPR base editing")
    year_from, year_to = st.slider("Publication years", 1990, THIS_YEAR, (2012, THIS_YEAR))
    min_citations = st.number_input("Minimum citations", 0, 10_000, 5)
    types = st.multiselect("Work types", ["article", "review", "preprint"], default=["article", "review"])
    max_results = st.number_input("Max papers to fetch", 100, 20_000, 2000, step=100)
    typed_key = st.text_input("OpenAlex API key (optional)", type="password",
                              help="Free at openalex.org/settings/api. Leave blank to use the app's default.")
    api_key = typed_key or shared_key()
    if not typed_key and shared_key():
        st.caption("Using the app's shared API key.")
    filters = dict(year_from=year_from, year_to=year_to, min_citations=min_citations, types=types)

    c1, c2 = st.columns(2)
    do_count = c1.button("Check count")
    do_fetch = c2.button("Fetch", type="primary")

    if do_count and not use_mock:
        try:
            st.info(f"{get_client(api_key).count(query, **filters):,} works match")
        except Exception as e:  # network / API errors
            st.error(str(e))

    if do_fetch:
        try:
            if use_mock:
                st.session_state["works"] = mock_works()
            else:
                bar = st.progress(0.0, text="Fetching from OpenAlex...")
                raw = get_client(api_key).fetch(
                    query, max_results=int(max_results),
                    progress=lambda done, total: bar.progress(done / max(total, 1)), **filters)
                st.session_state["works"] = normalize_all(raw)
                bar.empty()
            st.session_state["query"] = "mock data" if use_mock else query
        except Exception as e:
            st.error(str(e))

works = st.session_state.get("works")
if not works:
    st.info("Enter keywords in the sidebar, check the count, then press Fetch. "
            "Tick 'Use mock data' to try the interface without network access.")
    st.stop()

# ---------------------------------------------------------------- main: tune the cutoffs
st.subheader(f"2. Tune the map: {st.session_state['query']} ({len(works):,} papers)")
k1, k2, k3, k4 = st.columns(4)
mode = k1.selectbox("Edge type", ["both", "cocitation", "citation"],
                    help="cocitation = papers cited together; citation = direct links")
min_cocitations = k2.slider("Min co-citations", 1, 10, 2,
                            help="Co-citation pairs seen fewer times are ignored. Direct citations are always kept.")
resolution = k3.slider("Resolution", 0.2, 3.0, 1.0, 0.1, help="Higher = more, smaller research lines")
min_size = k4.slider("Min cluster size", 2, 100, 10)
exclude_reviews = st.checkbox("Exclude reviews when clustering (shown separately as entry points)", True)

fingerprint = f"{len(works)}-{works[0]['id']}-{works[-1]['id']}"
res = run(works, fingerprint, mode, min_cocitations, resolution, min_size, exclude_reviews)

s = res.stats
st.write(f"**{s['clusters']} research lines** covering {s['clustered']:,} of {s['works']:,} papers "
         f"({s['unclustered']:,} unclustered, {s['edges']:,} graph edges)")
if res.summary.empty:
    st.warning("No clusters found. Lower 'Min cluster size' or 'Min co-citations', or fetch more papers.")
    st.stop()

st.dataframe(res.summary, hide_index=True)

# ---------------------------------------------------------------- inspect one line
st.subheader("3. Inspect a research line")
labels = dict(zip(res.summary.cluster, res.summary.label))
cid = st.selectbox("Research line", list(labels), format_func=lambda c: f"{c}: {labels[c]}")
d = res.detail[cid]
cols = ["year", "title", "in_cluster_cites", "cited_by", "cites_per_year", "url"]

t1, t2, t3 = st.tabs(["Key papers", "Reviews (entry points)", "Authors and timeline"])
with t1:
    st.caption("Ranked by citations from other papers in the same line. Sort by year for a reading path.")
    st.dataframe(d["papers"][cols], hide_index=True)
with t2:
    if d["reviews"].empty:
        st.write("No reviews attached to this line. Add 'review' to the work types and fetch again.")
    else:
        st.dataframe(d["reviews"][cols], hide_index=True)
with t3:
    left, right = st.columns(2)
    left.write("Most frequent last authors")
    left.dataframe(d["authors"], hide_index=True)
    right.write("Papers per year")
    right.bar_chart(d["years"])

st.download_button("Download all papers with clusters (CSV)", res.papers.to_csv(index=False),
                   "papers_with_clusters.csv", "text/csv")
