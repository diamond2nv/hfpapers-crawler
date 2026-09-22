# Item types — what a record *is*

> Why this exists, what was borrowed from Zotero, what was deliberately left out, and how to
> extend it. Code: `hfpapers/item_types.py` (vocabulary + rules), `hfpapers/paper_store.py`
> (storage), `hfpclawer store types | classify | set-type` (CLI).

## 1. The problem

A store that holds preprints, journal articles, conference papers, company white papers and
the occasional thesis needs to answer "what *is* this record?" — and before v0.19.5 it could
not. `venue` was doing three jobs at once (container title, repository name, and sometimes an
arXiv category), 48% of rows had an empty venue, and material class was expressed as free-text
tags (`tag:not-peer-reviewed`) applied by hand to a handful of records.

The consequence is not cosmetic: citation discipline depends on knowing whether a claim comes
from a **peer-reviewed** source, and a query like "show me the journal articles about X" was
impossible to express.

## 2. What Zotero does (and what is worth copying)

Zotero itemises the world with a **closed vocabulary of 38 `itemType` values** and — this is
the important part — **gives each type its own field set**: a `journalArticle` has
`publicationTitle` / `volume` / `issue` / `pages`; a `conferencePaper` has `proceedingsTitle`
and `conferenceName`; a `report` has `reportNumber`, `institution` and `reportType`. Creators
are typed too (`author`, `editor`, `translator`), and attachments/notes are **child items**
rather than columns.

Three ideas are worth copying, in order of value:

1. **A closed vocabulary** with one type per record — a type is a fact you can query, not a
   sentence you have to parse.
2. **Fields belong to types.** "Which fields are meaningful" changes with the record shape;
   modelling that keeps empty columns from pretending to be data.
3. **Carrier form ≠ review status.** Zotero's `preprint` says nothing about quality; review
   status is derived downstream (by the reader, or by a tool like this one).

What is intentionally **not** copied: per-type field tables (our sources deliver one flat
metadata shape, and a 38-type × N-field schema would be all cost and no data), typed creators
(we store an authors string per record today), and child items (attachments live in
`data/pdfs` / `data/md_extracts` with their own audit trail).

## 3. Our design: three axes, kept apart

| Axis | Column | Answers | Values |
|:--|:--|:--|:--|
| **Carrier form** | `papers.item_type` | What *is* it? | the vocabulary below |
| **Container** | `papers.venue` | Where did it appear? | journal / proceedings / repository name (free text, unchanged) |
| **Provenance** | `papers.source` | How did it get here? | `import`, `downloader`, `orcid`, `cron:<topic>`, `manual-qq`, `cli` … |

Two more columns record the audit trail of the decision itself:
`item_type_src` (`derived` = a rule matched, `manual` = a human or a caller decided) and
`item_type_at`.

Keeping the axes apart is what makes the type trustworthy: `source='cron:fusion'` and
`item_type='preprint'` are both true and independent, whereas a single "category" column would
force a choice and lose information.

### The vocabulary

Zotero's names, our subset, plus one honest extension:

| item_type | Peer-reviewed | In Zotero | Typical evidence in this store |
|:--|:--|:--|:--|
| `journalArticle` | yes | yes | a DOI + a venue that is not a repository |
| `conferencePaper` | yes | yes | venue naming a proceedings/symposium/conference |
| `preprint` | no | yes | arXiv venue or category, arXiv id without a DOI, "under review" |
| `report` | no | yes | `tag:not-peer-reviewed`, "Technical Report"/"white paper" in the venue |
| `thesis` | no | yes | "thesis"/"dissertation"/"habilitation" as a **word** in venue or title |
| `book` / `bookSection` | yes | yes | manual (our sources rarely identify books) |
| `dataset` | no | yes | manual (e.g. a Zenodo data deposit) |
| `software` | no | yes | manual (e.g. a code release that *is* the record) |
| `webpage` | no | yes | blog / news / url-only identifier |
| `unknown` | — | **our extension** | no rule matched |

`unknown` is a real answer. A plausible-looking `journalArticle` on a record nobody checked is
worse than an `unknown` that a human can fix in one command — and `store classify` reports the
two failure modes separately: *never classified* (`''`) versus *no rule matched* (`unknown`).

Peer-review status is derived from the type, never stored beside it:
`is_peer_reviewed(item_type) -> True | False | None` (`None` = the type doesn't decide it).

## 4. The derivation rules

`derive_item_type(venue, title, id_types, tags, has_code) -> (item_type, reason)`

Pure, ordered, and offline — first match wins, and the `reason` names both the rule and the
evidence, so a backfill can be reviewed line by line. Order matters in three places where a
naïve implementation got the store wrong:

1. **Explicit markers before naming heuristics** — `tag:not-peer-reviewed` and "Technical
   Report" beat any journal-looking string.
2. **"Not accepted yet" beats a conference acronym** — `arXiv:2508.04349 (ICLR 2026 under
   review)` is a **preprint**, not an ICLR paper. (Real record; it was mis-derived before this
   rule existed.)
3. **Marker matching is word-bounded, not substring** — `materials synthesis` must not fire the
   `thesis` marker, and `hypothesis` must not either; `Oracle` must not fire `acl`. (All three
   were real mis-derivations found while auditing the first backfill.)

A comma-separated list of arXiv categories (`cond-mat.mtrl-sci, physics.comp-ph`) is an arXiv
venue, not an "unknown".

### Extending the rules

Add a hint to the relevant tuple in `hfpapers/item_types.py` (`_PROCEEDINGS_HINTS`,
`_REPORT_VENUE_HINTS`, …) or add an ordered branch to `derive_item_type`, then add the case to
`tests/test_item_types.py::TestDerivation`. Keep the rules **mechanical** — a rule that needs a
model call belongs behind an extra, not in the classifier: the value here is that the same input
always yields the same type and the same stated reason.

## 5. Migration and backfill

* Schema: `papers.item_type` / `item_type_src` / `item_type_at`, added in `_init_db` as
  `ALTER TABLE … ADD COLUMN` (idempotent; migration v5). Existing DBs need no manual step —
  the first command that opens the store applies it.
* Backfill: `hfpclawer store classify` (dry run) then `--apply`. It only touches records whose
  type is empty or `unknown` unless `--all` is given, so re-running is safe and manual decisions
  are never silently overwritten by a rule.
* `--limit` caps **how many rows the dry run prints**; `--max` caps **how many records the pass
  processes** (default 0 = all candidates). They were one option once, and a backfill silently
  wrote 20 of 1182 records — display limits and work limits are different things.
* Manual correction: `hfpclawer store set-type <item_type> --sf-id <id>` (records
  `item_type_src='manual'`).
* Inventory: `hfpclawer store types` — the vocabulary, the store counts, and the two
  unclassified buckets.

## 6. Known limits

* **Books, datasets and software are never derived** — our adapters cannot distinguish them
  from other shapes, so they stay manual. Guessing produced a wrong `software` on the first
  backfill (a statistics paper with a code URL), which is why the rule was dropped.
* **`year` is not part of the decision.** Records whose year came from a wrongly attached DOI
  keep that year until the DOI is corrected; type derivation deliberately ignores it.
* **Venue text is still free-form.** Fixing that (normalised container names, ISSNs) is a
  separate problem, and `item_type` is what makes it tractable: different containers follow
  different rules.
* Peer-review status is **inferred from the carrier form**. A journal article in a predatory
  venue is still `journalArticle` with `is_peer_reviewed → True`; judging venues is out of scope.
