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
python cli.py --query "CRISPR base editing" --from 2015 --max 1000
streamlit run app.py                    # the interactive app
```

## OpenAlex API key (recommended)
Create a free account at https://openalex.org, copy your key from https://openalex.org/settings/api, then:
```
export OPENALEX_API_KEY=your_key        # Windows PowerShell: $env:OPENALEX_API_KEY="your_key"
```
Or paste it in the app sidebar. The API works without a key at a much smaller daily budget.

## How it works
1. `core/openalex.py` fetches works (cursor paging, SQLite cache in `cache.sqlite`, count preview).
2. `core/analysis.py` builds a citation graph, adds co-citation edges, clusters with Louvain,
   attaches reviews to the line they cite most, then ranks papers and labels each line.
3. `app.py` and `cli.py` are thin front ends over `core/`.

## Known limits of this minimal version
- Fetching returns the top-N papers by relevance, not the whole field. Raise "Max papers" if lines look thin.
- Only papers inside the fetched set are linked; no snowballing yet.
- Louvain runs in pure Python (networkx). Beyond roughly 20k papers, switch to `python-igraph` + `leidenalg`.
- Review detection relies on OpenAlex's `type` field, which is imperfect.
- Author names are not disambiguated (names only, no ID merging).

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
