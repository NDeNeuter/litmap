"""Minimal OpenAlex client: count preview, cursor-paged fetch, SQLite query cache."""
import hashlib
import json
import os
import sqlite3
import time

import requests

BASE_URL = "https://api.openalex.org/works"
SELECT = ("id,title,publication_year,cited_by_count,type,"
          "referenced_works,authorships,primary_topic")


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

    def fetch(self, query, max_results=2000, progress=None, use_cache=True, **filters):
        """Cursor-page through results (relevance order) and return raw works."""
        params = {**self.build_params(query, **filters), "select": SELECT}
        key = hashlib.sha256(json.dumps([params, max_results], sort_keys=True).encode()).hexdigest()
        if use_cache:
            row = self.db.execute("SELECT payload FROM queries WHERE key=?", (key,)).fetchone()
            if row:
                return json.loads(row[0])

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
        works = works[:max_results]

        self.db.execute("INSERT OR REPLACE INTO queries VALUES (?, ?)", (key, json.dumps(works)))
        self.db.commit()
        return works
