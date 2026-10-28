"""Minimal OpenAlex client: count preview, cursor-paged fetch, SQLite query cache."""
import hashlib
import json
import math
import os
import sqlite3
import time

import requests

BASE_URL = "https://api.openalex.org/works"
SELECT = ("id,title,publication_year,cited_by_count,type,"
          "referenced_works,authorships,primary_topic")


IDS_BATCH = 100   # 'openalex:W1|W2|...' accepts up to 100 ids per request
CITES_BATCH = 25  # seeds per 'cites:W1|W2|...' request; set to 1 if OR is rejected for 'cites'


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def short_id(url):
    """'https://openalex.org/W123' -> 'W123'."""
    return url.rsplit("/", 1)[-1] if url else url


def normalize(raw):
    """Flatten one raw OpenAlex work into the small dict the analysis uses."""
    authors = []
    for a in raw.get("authorships") or []:
        author = a.get("author") or {}
        authors.append({"id": short_id(author.get("id")),
                        "name": author.get("display_name"),
                        "position": a.get("author_position")})
    return {
        "id": short_id(raw["id"]),
        "title": raw.get("title") or "",
        "year": raw.get("publication_year"),
        "cited_by": raw.get("cited_by_count") or 0,
        "type": raw.get("type"),
        "refs": [short_id(r) for r in raw.get("referenced_works") or []],
        "authors": authors,
        "topic": (raw.get("primary_topic") or {}).get("display_name"),
    }


def normalize_all(raws):
    """Normalize, drop works without title/year, and de-duplicate by id."""
    out = {}
    for r in raws:
        w = normalize(r)
        if w["title"] and w["year"]:
            out[w["id"]] = w
    return list(out.values())


class OpenAlexClient:
    def __init__(self, api_key=None, cache_path="cache.sqlite", session=None, pause=0.1):
        self.api_key = api_key or os.environ.get("OPENALEX_API_KEY")
        self.session = session or requests.Session()
        self.pause = pause
        self.db = sqlite3.connect(cache_path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS queries (key TEXT PRIMARY KEY, payload TEXT)")
        self.db.commit()

    # ---- request helpers -------------------------------------------------
    @staticmethod
    def build_params(query, year_from=None, year_to=None, min_citations=0, types=None):
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{int(year_from)}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{int(year_to)}-12-31")
        if min_citations and min_citations > 0:
            filters.append(f"cited_by_count:>{int(min_citations) - 1}")  # i.e. >= min_citations
        if types:
            filters.append("type:" + "|".join(types))
        params = {"search": query, "per_page": 100}
        if filters:
            params["filter"] = ",".join(filters)
        return params

    def _get(self, params, retries=5):
        params = dict(params)
        if self.api_key:
            params["api_key"] = self.api_key
        for attempt in range(retries):
            r = self.session.get(BASE_URL, params=params, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)  # exponential backoff
                continue
            raise RuntimeError(f"OpenAlex error {r.status_code}: {r.text[:300]}")
        raise RuntimeError("OpenAlex: too many retries")

    # ---- public API ------------------------------------------------------
    def count(self, query, **filters):
        """How many works match? One tiny request, nothing downloaded."""
        params = {**self.build_params(query, **filters), "per_page": 1, "select": "id"}
        return self._get(params)["meta"]["count"]

    def _paged(self, params, max_results, progress=None):
        """Follow cursor paging until max_results works or no more pages."""
        works, cursor, total = [], "*", max_results
        while len(works) < max_results:
            data = self._get({**params, "cursor": cursor})
            batch = data.get("results", [])
            if not batch:
                break
            works.extend(batch)
            total = min(max_results, data.get("meta", {}).get("count", max_results))
            if progress:
                progress(min(len(works), total), total)
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(self.pause)
        return works[:max_results]

    def _cached(self, key_obj, compute, use_cache=True):
        key = hashlib.sha256(json.dumps(key_obj, sort_keys=True).encode()).hexdigest()
        if use_cache:
            row = self.db.execute("SELECT payload FROM queries WHERE key=?", (key,)).fetchone()
            if row:
                return json.loads(row[0])
        value = compute()
        self.db.execute("INSERT OR REPLACE INTO queries VALUES (?, ?)", (key, json.dumps(value)))
        self.db.commit()
        return value

    def fetch(self, query, max_results=200, progress=None, use_cache=True, **filters):
        """Seed pass: the most relevant works for a keyword query (relevance order)."""
        params = {**self.build_params(query, **filters), "select": SELECT}
        return self._cached([params, max_results], lambda: self._paged(params, max_results, progress), use_cache)

    # ---- first-neighbour pass ---------------------------------------------
    def fetch_by_ids(self, ids, progress=None):
        """Metadata for works we only know by id (the papers the seeds cite)."""
        ids, out = sorted(ids), []
        for i, batch in enumerate(_chunks(ids, IDS_BATCH)):
            params = {"filter": "openalex:" + "|".join(batch), "per_page": 100, "select": SELECT}
            out.extend(self._cached(["ids", params], lambda p=params: self._paged(p, 100)))
            if progress:
                progress(min((i + 1) * IDS_BATCH, len(ids)), len(ids))
        return out

    @staticmethod
    def _cites_params(seed_batch):
        return {"filter": "cites:" + "|".join(seed_batch), "per_page": 100, "select": SELECT,
                "sort": "cited_by_count:desc"}

    def count_citing(self, seed_ids):
        """Upper estimate of citing works (papers citing several seeds are counted once per batch)."""
        return sum(self._get({**self._cites_params(b), "per_page": 1, "select": "id"})["meta"]["count"]
                   for b in _chunks(sorted(seed_ids), CITES_BATCH))

    def fetch_citing(self, seed_ids, max_results=10000, progress=None):
        """Works citing any seed. The cap is split evenly over seed batches; within a batch the
        most-cited citing works are kept first."""
        batches = list(_chunks(sorted(seed_ids), CITES_BATCH))
        per_batch = max(1, math.ceil(max_results / max(1, len(batches))))
        out = {}
        for i, b in enumerate(batches):
            p = self._cites_params(b)
            for w in self._cached(["cites", p, per_batch], lambda p=p: self._paged(p, per_batch)):
                out[w["id"]] = w
            if progress:
                progress(i + 1, len(batches))
        return list(out.values())


def assign_roles(works, seed_ids):
    """role = seed | cited (referenced by a seed) | citing (cites a seed) | both | other."""
    seed_ids = set(seed_ids)
    cited = {r for w in works if w["id"] in seed_ids for r in w["refs"]}
    for w in works:
        if w["id"] in seed_ids:
            w["role"] = "seed"
            continue
        is_cited = w["id"] in cited
        is_citing = any(r in seed_ids for r in w["refs"])
        w["role"] = ("both" if is_cited and is_citing else "cited" if is_cited
                     else "citing" if is_citing else "other")
    return works


def expand_corpus(client, seeds, max_citing=10000, progress=None):
    """Add all first neighbours of the seeds: papers they cite and papers citing them."""
    say = progress or (lambda *a: None)
    seed_ids = {w["id"] for w in seeds}
    cited_ids = {r for w in seeds for r in w["refs"]} - seed_ids
    cited = normalize_all(client.fetch_by_ids(cited_ids, lambda d, t: say("Fetching cited papers", d, t)))
    citing = normalize_all(client.fetch_citing(seed_ids, max_citing, lambda d, t: say("Fetching citing papers", d, t)))
    by_id = {w["id"]: w for w in seeds}
    for w in cited + citing:
        by_id.setdefault(w["id"], w)
    return assign_roles(list(by_id.values()), seed_ids)


def build_corpus(client, query, n_seeds=200, expand=True, max_citing=10000, progress=None, **filters):
    """Two-pass corpus: top-n_seeds relevant works, then (optionally) all their first neighbours."""
    say = progress or (lambda *a: None)
    seeds = normalize_all(client.fetch(query, max_results=n_seeds,
                                       progress=lambda d, t: say("Fetching seed papers", d, t), **filters))
    seeds = assign_roles(seeds, {w["id"] for w in seeds})
    return expand_corpus(client, seeds, max_citing, progress) if expand else seeds
