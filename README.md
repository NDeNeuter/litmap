# Research line explorer (minimal version)

Finds the main research lines in a field by clustering the citation structure of papers from OpenAlex.

## Setup
```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run
```
python -m unittest discover -s tests    # core tests (no network needed)
python cli.py --mock                    # try the pipeline on synthetic data
python cli.py --query "CRISPR base editing" --count-only    # FIRST real API call: just a count
python cli.py --query "CRISPR base editing" --seeds 200 --graph-line 1
streamlit run app.py                    # the interactive app
```

## OpenAlex API key (recommended)
Create a free account at https://openalex.org, copy your key from https://openalex.org/settings/api, then:
```
export OPENALEX_API_KEY=your_key        # Windows PowerShell: $env:OPENALEX_API_KEY="your_key"
```
Or paste it in the app sidebar. The API works without a key at a much smaller daily budget.

## How it works
1. **Seeds.** `core/openalex.py` fetches the 200 most relevant papers for your keywords (count preview first).
2. **First neighbours.** It then fetches every paper the seeds cite (`openalex:` ID batches) and every paper
   citing a seed (`cites:` filter, capped by "Max citing papers"). Roles are recorded: seed, cited, citing, both.
3. **Graph.** `core/analysis.py` builds a directed weighted graph. Edge u -> v means "v cites u" (cited paper to
   citing paper). The weight starts at 1 for a direct citation and grows by 1 every time two papers are
   co-cited by a paper in the corpus. Co-cited pairs without a direct citation get an edge from the older to
   the newer paper.
4. **Research lines.** `core/clustering.py` is a PLACEHOLDER (Louvain on the undirected weights, reviews
   attached afterwards). Replace `cluster_lines` with your own method.
5. **Inspect.** Per line: key papers, reviews, the line's graph (force or timeline layout), and frequently
   co-occurring author groups (Apriori frequent itemsets, `core/authors.py`).

## Cost and size
The OpenAlex free key allows roughly 10,000 list requests per day (100 records each). Seeds cost ~2 requests,
cited papers ~1 per 100 IDs, citing papers ~1 per 100 records. The graph step is the real limit: memory and time
grow with the number of papers and with co-citation pairs. Raise "Min co-citations" if it gets slow.

## Known limits
- Neighbours of the seeds are not filtered by year or type; only the seeds are.
- When the citing-paper cap bites, the most-cited citing papers are kept (biases toward older work).
- Using OR in the `cites:` filter is assumed to work like OR elsewhere in OpenAlex. If the first real fetch
  fails, set `CITES_BATCH = 1` in `core/openalex.py`.
- Review detection relies on OpenAlex's `type` field, which is imperfect.
- Authors are matched by OpenAlex author id, which is imperfect; papers with more than 25 authors are ignored.

## Deploy on Streamlit Community Cloud (from GitHub)
1. Create an empty repository on github.com (no README), then from the project folder:
   ```
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-username>/litmap.git
   git push -u origin main
   ```
2. Go to https://share.streamlit.io, sign in with GitHub, choose "Create app" / "New app".
3. Pick the repository and branch `main`, set the main file path to `app.py`.
4. Open "Advanced settings" and select Python 3.12.
5. Deploy. The first build takes a few minutes; you get a `*.streamlit.app` URL.

### API key on a public app
Anyone with the URL can use your app. If you store `OPENALEX_API_KEY` in the app's Secrets, every visitor
spends YOUR daily OpenAlex budget. Safer options: leave the secret out and let each visitor paste their own free
key in the sidebar, or restrict the app to specific viewers in the app's sharing settings before adding the secret.
Secrets format (Advanced settings -> Secrets):
```
OPENALEX_API_KEY = "your_key"
```
The on-disk cache (`cache.sqlite`) is wiped when the app restarts.
