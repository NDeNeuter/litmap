import itertools
import random
import unittest
from collections import Counter

from core import openalex as oa
from core.analysis import analyze, build_graph, line_members
from core.authors import author_teams, frequent_itemsets
from core.mock import mock_corpus, mock_raw_works, mock_works
from core.openalex import OpenAlexClient, assign_roles, build_corpus, normalize_all
from core.plot import draw_line_graph


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.text = payload, status, str(payload)

    def json(self):
        return self._payload


class FakeAPI:
    """Imitates the OpenAlex endpoints we use: search, openalex:<ids>, cites:<ids>, cursor paging."""
    def __init__(self, n_per_topic=60):
        self.raw = mock_raw_works(n_per_topic=n_per_topic, seed=1)
        random.Random(5).shuffle(self.raw)  # 'relevance' order
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        filt = dict(x.split(":", 1) for x in params.get("filter", "").split(",") if x)
        sid = oa.short_id
        if "search" in params:
            pool = self.raw
        elif "openalex" in filt:
            ids = set(filt["openalex"].split("|"))
            pool = [w for w in self.raw if sid(w["id"]) in ids]
        elif "cites" in filt:
            ids = set(filt["cites"].split("|"))
            pool = [w for w in self.raw if any(sid(r) in ids for r in w["referenced_works"])]
        else:
            pool = []
        if params.get("sort") == "cited_by_count:desc":
            pool = sorted(pool, key=lambda w: -w["cited_by_count"])
        per = params["per_page"]
        start = 0 if params.get("cursor", "*") == "*" else int(params["cursor"])
        nxt = str(start + per) if start + per < len(pool) else None
        return FakeResponse({"meta": {"count": len(pool), "next_cursor": nxt}, "results": pool[start:start + per]})


def mk(i, year, refs=(), typ="article"):
    return {"id": i, "title": f"paper {i}", "year": year, "cited_by": 0, "type": typ,
            "refs": list(refs), "authors": [], "topic": None}


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.client = OpenAlexClient(api_key="KEY", cache_path=":memory:", session=self.api, pause=0)

    def test_params(self):
        p = OpenAlexClient.build_params("crispr", 2015, 2024, 5, ["article", "review"])
        self.assertIn("from_publication_date:2015-01-01", p["filter"])
        self.assertIn("cited_by_count:>4", p["filter"])
        self.assertIn("type:article|review", p["filter"])

    def test_seed_fetch_limits_and_caches(self):
        works = self.client.fetch("crispr", max_results=200)
        self.assertEqual(len(works), 200)
        n = len(self.api.calls)
        self.client.fetch("crispr", max_results=200)
        self.assertEqual(len(self.api.calls), n)

    def test_retry_on_429(self):
        class Flaky(FakeAPI):
            n = 0
            def get(self, url, params=None, timeout=None):
                Flaky.n += 1
                return FakeResponse({}, 429) if Flaky.n == 1 else super().get(url, params, timeout)
        oa.time.sleep = lambda s: None
        c = OpenAlexClient(cache_path=":memory:", session=Flaky(), pause=0)
        self.assertEqual(c.count("x"), 240)


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.client = OpenAlexClient(cache_path=":memory:", session=self.api, pause=0)

    def test_two_pass_corpus_is_the_first_neighbourhood(self):
        corpus = build_corpus(self.client, "x", n_seeds=20)
        seeds = {w["id"] for w in corpus if w["role"] == "seed"}
        self.assertEqual(len(seeds), 20)
        ids = {w["id"] for w in corpus}
        expected_cited = {r for w in corpus if w["id"] in seeds for r in w["refs"]}
        self.assertTrue(expected_cited <= ids)  # everything the seeds cite is present
        every = normalize_all(self.api.raw)
        expected_citing = {w["id"] for w in every if any(r in seeds for r in w["refs"])}
        self.assertTrue(expected_citing <= ids)  # everything citing a seed is present
        self.assertEqual(ids, seeds | expected_cited | expected_citing)  # and nothing else
        self.assertTrue(all(w["role"] in ("seed", "cited", "citing", "both") for w in corpus))

    def test_batches_respect_api_limits(self):
        build_corpus(self.client, "x", n_seeds=60)
        for p in self.api.calls:
            f = p.get("filter", "")
            if f.startswith("openalex:"):
                self.assertLessEqual(len(f[9:].split("|")), oa.IDS_BATCH)
            if f.startswith("cites:"):
                self.assertLessEqual(len(f[6:].split("|")), oa.CITES_BATCH)

    def test_citing_cap(self):
        full = build_corpus(self.client, "x", n_seeds=20, max_citing=10_000)
        capped = build_corpus(OpenAlexClient(cache_path=":memory:", session=FakeAPI(), pause=0),
                              "x", n_seeds=20, max_citing=10)
        n = lambda c: sum(1 for w in c if w["role"] in ("citing", "both"))
        self.assertLess(n(capped), n(full))

    def test_seeds_only(self):
        corpus = build_corpus(self.client, "x", n_seeds=15, expand=False)
        self.assertEqual({w["role"] for w in corpus}, {"seed"})
        self.assertEqual(len(corpus), 15)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.works = [mk("A", 2000), mk("B", 2005, ["A"]), mk("C1", 2010, ["A", "B"]), mk("C2", 2011, ["A", "B"]),
                      mk("Y", 1999), mk("Z", 2003), mk("W1", 2010, ["Y", "Z"]), mk("W2", 2011, ["Y", "Z"])]

    def test_direction_cited_to_citing(self):
        D = build_graph(self.works)
        self.assertEqual(D["A"]["B"]["citation"], 1)      # B cites A  =>  A -> B
        self.assertFalse(D.has_edge("B", "A"))
        self.assertTrue(D.has_edge("A", "C1") and D.has_edge("B", "C2"))

    def test_cocitation_raises_weight(self):
        D = build_graph(self.works)
        self.assertEqual(D["A"]["B"]["cocitation"], 2)    # C1 and C2 both cite A and B
        self.assertEqual(D["A"]["B"]["weight"], 3)        # 1 direct + 2 co-citations

    def test_cocited_only_pair_points_old_to_new(self):
        D = build_graph(self.works)
        self.assertEqual(D["Y"]["Z"]["citation"], 0)
        self.assertEqual(D["Y"]["Z"]["cocitation"], 2)
        self.assertFalse(D.has_edge("Z", "Y"))

    def test_min_cocitations_threshold(self):
        D = build_graph(self.works, min_cocitations=3)
        self.assertFalse(D.has_edge("Y", "Z"))
        self.assertEqual(D["A"]["B"]["weight"], 1)

    def test_review_cocitations_ignored_by_default(self):
        works = [mk("A", 2000), mk("B", 2001), mk("R", 2010, ["A", "B"], typ="review")]
        self.assertFalse(build_graph(works, min_cocitations=1).has_edge("A", "B"))
        self.assertTrue(build_graph(works, min_cocitations=1, count_review_cocitations=True).has_edge("A", "B"))


class AnalysisTests(unittest.TestCase):
    def test_recovers_planted_lines_on_full_corpus(self):
        works = mock_works()
        res = analyze(works)
        truth = {w["id"]: w["topic"] for w in works}
        self.assertEqual(res.stats["clusters"], 4)
        for c in res.summary.cluster:
            topics = Counter(truth[i] for i in line_members(res, c))
            self.assertGreaterEqual(topics.most_common(1)[0][1] / sum(topics.values()), 0.9, topics)

    def test_works_on_a_neighbourhood_corpus(self):
        res = analyze(mock_corpus(40), min_size=8)
        self.assertGreaterEqual(res.stats["clusters"], 2)
        self.assertEqual(len(res.papers), res.stats["works"])

    def test_min_size_filters(self):
        res = analyze(mock_works(), min_size=10_000)
        self.assertEqual(res.stats["clusters"], 0)
        self.assertTrue(res.summary.empty)

    def test_reviews_attached_to_a_line(self):
        res = analyze(mock_works())
        revs = res.papers[(res.papers.type == "review") & (res.papers.cluster > 0)]
        self.assertGreater(len(revs), 0)


class AuthorTests(unittest.TestCase):
    def test_apriori_matches_brute_force(self):
        rng = random.Random(3)
        baskets = [set(rng.sample("ABCDEFGH", rng.randint(1, 5))) for _ in range(60)]
        got = frequent_itemsets(baskets, min_support=4, max_size=3)
        expected = {}
        for k in (1, 2, 3):
            for combo in itertools.combinations("ABCDEFGH", k):
                c = sum(1 for b in baskets if set(combo) <= b)
                if c >= 4:
                    expected[frozenset(combo)] = c
        self.assertEqual(got, expected)

    def test_large_baskets_ignored(self):
        baskets = [set("ABC")] * 3 + [set("ABCDEFGHIJ")] * 5
        got = frequent_itemsets(baskets, min_support=3, max_basket=5)
        self.assertEqual(got[frozenset("AB")], 3)

    def test_closed_only_removes_redundant_subgroups(self):
        works = [{"authors": [{"id": k, "name": k, "position": "middle"} for k in "XYZ"]} for _ in range(4)]
        closed = author_teams(works, min_support=3, max_size=3)
        self.assertEqual(list(closed.authors), ["X; Y; Z"])
        self.assertEqual(len(author_teams(works, min_support=3, max_size=3, closed_only=False)), 4)

    def test_planted_teams_recovered_per_line(self):
        res = analyze(mock_works())
        for c in res.summary.cluster:
            teams = author_teams([res.by_id[i] for i in line_members(res, c)], min_support=5)
            self.assertGreaterEqual(len(teams), 1)
            top = teams.iloc[0]
            self.assertEqual(top["size"], 3)
            self.assertIn("team", top.authors)


class PlotTests(unittest.TestCase):
    def test_both_layouts_render(self):
        res = analyze(mock_works())
        members = line_members(res, 1)
        for layout in ("force", "timeline"):
            fig = draw_line_graph(res.graph, res.by_id, members, layout=layout, max_nodes=60)
            fig.savefig("/tmp/_plot_test.png")


if __name__ == "__main__":
    unittest.main()
