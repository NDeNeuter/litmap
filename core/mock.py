"""Synthetic OpenAlex-shaped data with planted research lines, for testing without network."""
import random

from .openalex import normalize_all

TOPICS = {
    "gene editing": ["crispr", "cas9", "genome", "editing", "guide", "nuclease", "off-target"],
    "immunotherapy": ["checkpoint", "tcell", "pd-1", "tumor", "immune", "antibody", "response"],
    "microbiome": ["gut", "microbiota", "bacteria", "diversity", "metabolite", "sequencing", "dysbiosis"],
    "neurodegeneration": ["amyloid", "tau", "alzheimer", "neuron", "synaptic", "cognitive", "aggregation"],
}
GENERIC = ["novel", "role", "mechanisms", "analysis", "approach", "evidence", "patients", "model"]


def mock_raw_works(n_per_topic=100, year_from=2005, year_to=2024, seed=0):
    rng = random.Random(seed)
    topics = list(TOPICS)
    pis = {t: [f"{t.split()[0].title()} PI {i}" for i in range(4)] for t in topics}

    papers = [{"topic": t, "year": rng.randint(year_from, year_to)}
              for t in topics for _ in range(n_per_topic)]
    papers.sort(key=lambda p: p["year"])
    for i, p in enumerate(papers):
        p["id"] = f"W{1000 + i}"
        p["type"] = "review" if rng.random() < 0.05 else "article"

    indeg = {p["id"]: 0 for p in papers}
    earlier = {t: [] for t in topics}
    for p in papers:
        t = p["topic"]
        own = earlier[t]
        others = [q for u in topics if u != t for q in earlier[u]]
        n_refs = 40 if p["type"] == "review" else rng.randint(8, 15)
        refs = set()
        if own:  # preferential attachment inside the same line
            weights = [1 + indeg[q["id"]] for q in own]
            refs |= {q["id"] for q in rng.choices(own, weights=weights, k=int(n_refs * 0.85))}
        if others:  # a little cross-topic citation noise
            refs |= {q["id"] for q in rng.choices(others, k=max(1, int(n_refs * 0.15)))}
        for r in refs:
            indeg[r] += 1
        p["refs"] = sorted(refs)
        earlier[t].append(p)

    raws = []
    for p in papers:
        t = p["topic"]
        words = rng.sample(TOPICS[t], 4) + rng.sample(GENERIC, 2)
        rng.shuffle(words)
        names = [f"Author {rng.randint(1, 400)}" for _ in range(rng.randint(2, 4))]
        last = rng.choice(pis[t]) if rng.random() < 0.6 else f"Author {rng.randint(1, 400)}"
        authorships = ([{"author_position": "first", "author": {"id": "https://openalex.org/A0", "display_name": names[0]}}]
                       + [{"author_position": "middle", "author": {"id": "https://openalex.org/A0", "display_name": n}} for n in names[1:]]
                       + [{"author_position": "last", "author": {"id": "https://openalex.org/A0", "display_name": last}}])
        raws.append({
            "id": f"https://openalex.org/{p['id']}",
            "title": " ".join(words).capitalize(),
            "publication_year": p["year"],
            "cited_by_count": indeg[p["id"]] * 3 + rng.randint(0, 5),
            "type": p["type"],
            "referenced_works": [f"https://openalex.org/{r}" for r in p["refs"]],
            "authorships": authorships,
            "primary_topic": {"display_name": t.title()},
        })
    return raws


def mock_works(**kwargs):
    return normalize_all(mock_raw_works(**kwargs))
