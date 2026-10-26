# Title → arXiv ID reverse lookup

`hfpapers/arxiv_lookup.py` (+ `hfpclawer lookup-id` / `hfpclawer lookup-ids`) resolves a paper **title**
to an arXiv ID. Every rule below is a measured failure it prevents (2026-09-23) — the recipe used to
live in agent prose and went wrong the same ways every time.

## Two gates, then a reason

| Stage | Rule | Why |
|:--|:--|:--|
| normalise | lowercase, drop punctuation, collapse whitespace | case and typography must not decide a match |
| accept | exact → containment (*shorter side ≥ 3 words*) → ratio ≥ `--threshold` (default 0.60) | containment handles "short query vs full title"; the ratio floor rejects a *plausible neighbour* |

The ratio floor is the important half: a search for *"Towards grounded autonomous research"* returns a
driving benchmark that is **not** the paper you wanted (ratio ≈ 0.36). The gate turns "closest match"
into "match or nothing".

| `reason` (printed by `lookup-id`) | meaning | action |
|:--|:--|:--|
| `exact` / `prefix` / `ratio` | accepted (which gate matched) | use the id |
| `below-threshold` | candidates existed, none matched | sharpen the title, or move `--threshold` |
| `no-candidate` | the API answered and has nothing | the phrasing is probably not the paper's title |
| `blocked` | transport blocked or throttled | back off and retry — **not** "the paper does not exist" |

Exit code 0 = resolved, 1 = not, 2 = bad input.

## Four quirks this module encapsulates

1. **HTTPS only.** `http://export.arxiv.org` answers 301; a client that does not follow redirects sees a
   0-byte body that looks exactly like "no results".
2. **Burst throttling.** ~40 calls in a few minutes earn a 0-byte response. `Pacing` keeps ≥3s between
   calls and treats a 0-byte body as *blocked*, sleeping an escalating backoff (5s → 15s → 45s).
3. **Query mangling.** `urllib.parse.quote()` with defaults turns `+` into `%2B`, so a `+AND+` query
   silently matches nothing. Titles are encoded phrase-wise (`ti:%22…%22`) with the prefix left literal.
4. **Client fingerprint.** The *same* URL answered **406 for `urllib`** (any UA/`Accept` combination)
   while `requests` and `curl` got 200 — the API's edge judges the client, not only the query.
   `_http_get` therefore uses `requests` first (a core dependency) and falls back to `urllib`.

## Usage

```bash
hfpclawer lookup-id "Agora: Git as Shared Memory for Collective AutoResearch"   # ✅ 2609.18094
hfpclawer lookup-id "Some Title" --json
hfpclawer lookup-ids --file titles.txt              # paced batch: one API call per line
printf '%s\n' "Title A" "Title B" | hfpclawer lookup-ids --file - --json
```

```python
from hfpapers.arxiv_lookup import lookup_title, lookup_titles, Pacing

r = lookup_title("Toward Autonomous O-RAN: A Multi-Scale Agentic AI Framework")   # → 2602.14117
print(r.arxiv_id, r.reason, r.ratio, r.categories)      # prefix 1.0 ['cs.NI', 'cs.AI']

for r in lookup_titles(["Title A", "Title B"]):          # one shared Pacing for the batch
    print(r.query, r.reason)
```

## Related

* `docs/USAGE.md` — fetching the payload once you have the ID (`hfpclawer fetch`)
* `docs/NETWORK.md` — the transport ladder (TCP → QUIC → browser hint) and its audit rows
