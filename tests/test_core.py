import unittest
from collections import Counter

from core.analysis import analyze
from core.mock import mock_raw_works, mock_works
from core.openalex import OpenAlexClient, normalize, normalize_all


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.text = payload, status, str(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Serves 250 fake works in pages of 100 using cursor paging; records every call."""
    def __init__(self):
        self.calls = []
        self.raw = mock_raw_works(n_per_topic=70)[:250]

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        if params.get("per_page") == 1:
            return FakeResponse({"meta": {"count": 250}, "results": [{"id": "x"}]})
        start = 0 if params["cursor"] == "*" else int(params["cursor"])
        page = self.raw[start:start + 100]
        nxt = str(start + 100) if start + 100 < len(self.raw) else None
        return FakeResponse({"meta": {"count": 250, "next_cursor": nxt}, "results": page})


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.client = OpenAlexClient(api_key="KEY", cache_path=":memory:", session=self.session, pause=0)

    def test_params(self):
        p = OpenAlexClient.build_params("crispr", 2015, 2024, 5, ["article", "review"])
        self.assertEqual(p["search"], "crispr")
        self.assertIn("from_publication_date:2015-01-01", p["filter"])
        self.assertIn("to_publication_date:2024-12-31", p["filter"])
        self.assertIn("cited_by_count:>4", p["filter"])
        self.assertIn("type:article|review", p["filter"])

    def test_count_and_key(self):
        self.assertEqual(self.client.count("crispr"), 250)
        self.assertEqual(self.session.calls[0]["api_key"], "KEY")

    def test_paging_progress_and_cache(self):
        seen = []
        works = self.client.fetch("crispr", max_results=1000, progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(len(works), 250)
        self.assertEqual(seen[-1], (250, 250))
        n_calls = len(self.session.calls)
        self.assertEqual(n_calls, 3)
        self.client.fetch("crispr", max_results=1000)  # served from cache
        self.assertEqual(len(self.session.calls), n_calls)

    def test_max_results_truncates(self):
        self.assertEqual(len(self.client.fetch("crispr", max_results=120)), 120)

    def test_retry_on_429(self):
        class Flaky(FakeSession):
            n = 0
            def get(self, url, params=None, timeout=None):
                Flaky.n += 1
                return FakeResponse({}, 429) if Flaky.n == 1 else super().get(url, params, timeout)
        import core.openalex as oa
        oa.time.sleep = lambda s: None
        c = OpenAlexClient(cache_path=":memory:", session=Flaky(), pause=0)
        self.assertEqual(c.count("x"), 250)


class NormalizeTests(unittest.TestCase):
    def test_normalize(self):
        w = normalize_all(mock_raw_works(n_per_topic=5))[0]
        self.assertTrue(w["id"].startswith("W"))
        self.assertTrue(all(r.startswith("W") for r in w["refs"]))
        self.assertIn("last", {a["position"] for a in w["authors"]})

    def test_drops_incomplete(self):
        self.assertEqual(normalize_all([{"id": "https://openalex.org/W1", "title": None, "publication_year": 2020}]), [])


class AnalysisTests(unittest.TestCase):
    def test_recovers_planted_lines(self):
        works = mock_works()
        res = analyze(works)
        truth = {w["id"]: w["topic"] for w in works}
        self.assertEqual(res.stats["clusters"], 4)
        for c in res.summary.cluster:
            topics = Counter(truth[i] for i in res.papers.loc[res.papers.cluster == c, "id"])
            purity = topics.most_common(1)[0][1] / sum(topics.values())
            self.assertGreaterEqual(purity, 0.9, f"cluster {c} impure: {topics}")

    def test_every_work_accounted_for(self):
        works = mock_works()
        res = analyze(works)
        self.assertEqual(len(res.papers), len(works))

    def test_reviews_attached_not_clustered_on(self):
        res = analyze(mock_works(), exclude_reviews=True)
        revs = res.papers[(res.papers.type == "review") & (res.papers.cluster > 0)]
        self.assertGreater(len(revs), 0)
        self.assertTrue(all(res.summary.n_reviews >= 0))

    def test_min_size_filters(self):
        res = analyze(mock_works(), min_size=10_000)
        self.assertEqual(res.stats["clusters"], 0)
        self.assertTrue(res.summary.empty)

    def test_all_modes_run(self):
        for mode in ("citation", "cocitation", "both"):
            self.assertGreaterEqual(analyze(mock_works(), mode=mode).stats["clusters"], 1)


if __name__ == "__main__":
    unittest.main()
