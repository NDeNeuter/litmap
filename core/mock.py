"""Synthetic OpenAlex-shaped data with planted research lines, for testing without network."""
import random
import zlib

from .openalex import assign_roles, normalize_all

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
    teams = {t: [[f"{t.split()[0].title()} team{j} member{k}" for k in range(3)] for j in range(2)]
             for t in topics}  # two 3-person labs per research line

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
        if rng.random() < 0.7:  # a whole lab co-authors, plus 0-2 outsiders
            team = rng.choice(teams[t])
            names = [team[0]] + [f"Author {rng.randint(1, 400)}" for _ in range(rng.randint(0, 2))] + team[1:]
        else:
            names = [f"Author {rng.randint(1, 400)}" for _ in range(rng.randint(3, 5))]
        names = list(dict.fromkeys(names))
        authorships = [{"author_position": "first" if i == 0 else "last" if i == len(names) - 1 else "middle",
                        "author": {"id": f"https://openalex.org/A{zlib.crc32(n.encode())}", "display_name": n}}
                       for i, n in enumerate(names)]
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


def mock_corpus(n_seeds=40, expand=True, seed=0):
    """Mimic the two-pass fetch: random seeds, then everything citing or cited by them."""
    universe = mock_works()
    seed_ids = {w["id"] for w in random.Random(seed).sample(universe, n_seeds)}
    if not expand:
        return assign_roles([w for w in universe if w["id"] in seed_ids], seed_ids)
    cited = {r for w in universe if w["id"] in seed_ids for r in w["refs"]}
    keep = [w for w in universe
            if w["id"] in seed_ids or w["id"] in cited or any(r in seed_ids for r in w["refs"])]
    return assign_roles(keep, seed_ids)
