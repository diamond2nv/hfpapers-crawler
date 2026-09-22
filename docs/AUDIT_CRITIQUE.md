# Design and audit critique

> What does this system return when it is asked a question it was never designed to answer
> honestly? The measurements below come from one afternoon (2026-09-19) spent auditing the live
> store — not from reading the code. Every number is reproducible from the DB and the snapshots
> under `/tmp`; none of it is an estimate.

## 0. What the pass actually measured

| Measurement | Value | How it was obtained |
|:--|:--|:--|
| `doi` identifiers in the store | 341 | `SELECT COUNT(*) FROM identifiers WHERE id_type='doi'` |
| Of those, **DOIs that belong to a different paper** | **25 removed** (13 from `confidence < 0.6`, 12 more found across the whole DOI population) | per-record Crossref title comparison, one by one |
| Records whose `year` was an **arXiv id prefix** (e.g. `2206.14588` → `year=2206`) | 14 | `WHERE year < 1900 OR year > 2100` |
| Records with `year = 0` | **687 / 1166 (59%)** | `SELECT COUNT(*) FROM papers WHERE year=0` |
| **Duplicate records** for the same paper | 18 groups; 16 records removed, 2 pairs deliberately kept (OSTI report ↔ journal paper) | normalised-title grouping |
| Records with no identifier at all | 21 → 5 after reconciliation | identifier count per record |
| Placeholder titles (`title = <identifier>`) | 3 found here; 102 in one earlier batch | title regex `^10\.\d{4,9}/` and the earlier incident |
| Titles that are *citation strings* (`Lu, L., Jin, P. … DeepONet`) | 17 | pattern `^[A-Z][a-z]+, [A-Z]\.` |
| Records with `audit_level > 0` | **66 / 1166 (5.7%)** — 1100 are level 0 | `GROUP BY audit_level` |
| Row-level mutation events in `ledger.jsonl` / `audit.db` | **0** | grep for delete/update events |

## 1. Provenance is asserted, not recorded — so errors can be mutually confirming

**What.** An identifier row records `source` (`cron:fusion`, `mdpi`) but *not how it was matched*:
which query produced it, against which index, at which similarity, by which code path. `confidence`
exists but nothing gates on it, and nothing downstream can tell a hand-checked DOI from an
auto-attached one.

**Evidence.** All 13 DOIs at `confidence < 0.6` were wrong — a 100% error rate that no consumer can
see, because `confidence` is not part of any query or report. In three cases the record's `venue`
string had itself been derived from the wrong DOI (`Sensors 23(10), 4882`, `Applied Sciences
13(1), 533`), so **venue and DOI agreed with each other while both being wrong**.

**Concrete wrong conclusion.** A citation-discipline query — "give me the peer-reviewed sources for
this claim" — returns those records as journal articles with a venue, a year and `verified = 1`. Any
consistency check that cross-validates `doi ↔ venue` passes, because the venue was copied from the
DOI. The system's own verification story confirms a falsehood. The corollary is worse: the auditor
cannot even *rank* records by trustworthiness, because trustworthiness was never stored.

**Structural fix.** Make attachment an appendix-like event: `identifier_events(sf_id, id_type,
id_value, action, method, query, similarity, source, actor, at)`, keep `confidence` on the event
rather than the row, and refuse to write an auto-attached identifier below a threshold unless the
caller passes `--accept-unverified`. Then "how did this DOI get here" is a query, not an
archaeology project.

## 2. The classifier cannot say "my evidence conflicts"

**What.** `derive_item_type` is first-match-wins over ordered hints. There is no way to express
conflicting evidence, no per-rule confidence, and no abstention when two sources disagree.

**Evidence.** Three records carried an arXiv identifier *and* a journal venue that had come from a
wrong DOI. The venue rule ran first, so they were classified `journalArticle` (`is_peer_reviewed →
True`) although they are preprints. Two more cases the other way: `npj Computational Materials
(arXiv preprint)` needed the word "preprint" in a venue string to avoid being read as a journal.

**Concrete wrong conclusion.** A review workflow asks "is this result peer reviewed?" and the store
answers *yes* for a preprint whose only defect is a stale venue string. Because `item_type` now
feeds `is_peer_reviewed()`, the wrong answer propagates with the authority of a derived field.

**Structural fix.** Let the rules emit *evidence items* (`("doi", 0.51, …)`, `("arxiv", 1.0, …)`)
and resolve them in one place, with an explicit `conflict` outcome that maps to `unknown` plus a
reason. Keep the vocabulary; change "first match wins" to "aggregate, then decide, or abstain".

## 3. No uniqueness invariant on the thing the system reasons over

**What.** `identifiers` has `UNIQUE(id_type, id_value)`; `papers` has nothing on title, DOI or
external identity. Duplicates are therefore legal, invisible, and only discoverable by the grouping
heuristics of whoever happens to audit.

**Evidence.** 18 duplicate groups. In the fusion slice (`cron:fusion`, 131 records) 9 were
duplicates — **≈7% of that slice**. Thirteen had the signature "one copy with identifiers, one copy
without", created by two different ingest paths five weeks apart.

**Concrete wrong conclusion.** Any count is inflated: "this topic has 12 papers" may describe 9
works, and the inflation is *not uniform* — it concentrates in the slices that were ingested twice,
i.e. exactly the slices used for trend claims. A `recommend` run can return the same work twice and
present it as two independent hits, which reads as corroboration.

**Structural fix.** Add a resolution key (`identity_key` = normalised DOI, else arXiv id, else
normalised title+year) with a uniqueness constraint, and make every ingest path resolve against it.
A `dedup --merge` command should move identifiers and enrich the survivor *by rule*, since today
that logic lives in ad-hoc scripts (mine printed "moved 0 identifiers" and dropped three arXiv ids
without failing).

## 4. The audit state machine measures process, not evidence quality

**What.** Three overlapping fields — `verified` (legacy boolean), `audit_level` 0–2, `suspect` — with
no documented precedence. `audit_level = 1` means "metadata verified (≥2 identifiers
cross-validated)".

**Evidence.** 5.7% of the store is above level 0 (66 records; 65 at level 1, 1 at level 2), 1100
records are level 0, and `suspect` is empty everywhere. The 25 wrong DOIs sat in the unaudited mass;
the record that started this cleanup had `verified = 1` *and* a DOI belonging to a 2013 Nature news
item — while its `year` (2013) and `venue` were inherited from that same wrong DOI.

**Concrete wrong conclusion.** "≥2 identifiers cross-validated" is satisfiable by **two mutually
wrong artifacts** (see §1). Level 1 is therefore not a quality statement, yet a consumer reading
`audit_level ≥ 1` as "checked against an independent source" gets assurance that was never earned.
With 94% of the store unaudited, an audit-derived statistic describes the audit queue, not the data.

**Structural fix.** Separate the axes explicitly: `metadata_source` per field (already partially
done in the importer), `cross_check` = *which independent sources agreed*, and `audit_level` for
workflow stage only. Add a store-level invariant report (`hfpclawer audit invariants`) that fails a
release when it regresses — see §5.

## 5. Green gates and corrupted data are decoupled

**What.** The release gate is `pytest tests/` + `ruff` + `pyright`, with the repo's own rule being
"clean for the files you touched" because the tree carries known pre-existing failures. Tests run
against fixture databases. No gate ever looks at the production artifact.

**Evidence.** Today: 105 targeted tests passed, the full suite showed the *same six* long-standing
failures (antlr4-backed LaTeX/Wolfram tests, two network-timeout tests), ruff and pyright carry
pre-existing errors — and in the same hour the artifact turned out to contain 25 foreign DOIs, 14
impossible years, 18 duplicate pairs and 21 identifier-less records. The most damaging incident
predates this pass: a batch import wrote 102 records whose `title` was the raw arXiv id while the CLI
printed `✅` for every one of them.

**Concrete wrong conclusion.** A release is declared healthy and a downstream report says "245 papers
ingested and verified" — the *count* is right, the *claim* is false: those records had no PDF, no
abstract, and a title equal to their identifier. Nothing in the gate output contradicts that report.

**Structural fix.** Promote data invariants to first-class gates, run against the real store in
read-only mode: `year` in `[1900, 2100]` or 0; every record has ≥1 identifier or an explicit
`no-identifier` flag; no `title` equal to an identifier; no duplicate `identity_key`; every DOI's
Crossref title matches the record (sampled, cached); no identifier attached with `confidence < 0.6`
unless tagged `accepted-unverified`. Each of these is cheap, deterministic, and would have caught
today's findings *before* they entered a report.

## 6. Data mutations have no audit trail

**What.** The repo invests heavily in append-only discipline for git and run-level accounting
(`ledger.jsonl`, `audit.db`), but **row-level** changes to the papers DB are unrecorded. Today's pass
deleted 25 identifiers, 16 records, moved 3 identifiers and rewrote 20 titles — and none of it
appears anywhere the system can query.

**Evidence.** `ledger.jsonl` (39.8 kB) contains zero delete/update events for these operations. The
only rollback path was a JSON snapshot I happened to write to `/tmp` before each destructive step.
When a bulk delete went wrong (a loose `LIKE 'Test%'` removed a real paper), recovery depended on a
three-day-old `papers_export_*.json` in `data/` — a lucky artifact, not a designed one.

**Concrete wrong conclusion.** Asked "who removed this DOI and why", the system cannot answer, so
the honest answer is "unknown" for changes that were in fact deliberate and documented in a chat
log. Worse, a future audit that finds a *correct* record missing its DOI has no way to distinguish
"never there" from "removed by a cleanup", and may re-add a wrong one.

**Structural fix.** Write deletions and rewrites as events — one append-only JSONL stream whose rows carry
`{table, key, before_hash, after_hash, actor, reason, snapshot_path}` — from a single `store` mutation API, and make
`store export` automatic before any destructive operation. Then "undo" is a feature, not a rescue.

## 7. Statistical layers sit on top of unmeasured label error

**What.** `relevance`, `rank` (LightGBM re-ranking), `recommend`, `check-new` and the wiki-facing
trend queries all consume `title`, `venue`, `year`, `identifier`. Every one of those fields has a
measured defect rate, and no layer reports the error rate of its own inputs.

**Evidence.** Foreign DOIs on ~7% of DOI-bearing records; `year = 0` on 59%; impossible years on 14;
duplicates concentrated in specific ingest slices; 17 titles that are citation strings rather than
titles. A re-ranker trained on such features learns *which cron job ingested a record* as much as
what it is about.

**Concrete wrong conclusion.** A trend note says a field "exploded in year X" because 14 records
carried a year that was an arXiv id prefix, or a recommendation is justified by a venue string that
came from a different paper. The failure is not that the statistics are wrong — it is that they are
**unfalsifiable**: nothing in the pipeline can say "input error rate was 3%, so treat differences
below that as noise".

**Structural fix.** Publish a per-field integrity report alongside every analytical output
(`year` coverage 41%, DOI verified share, duplicate rate per slice), and refuse to emit
trend/comparison claims for a slice whose integrity is below a stated floor. Calibration of the
statistics can then be argued for — today it cannot even be stated.

## 8. Semantics that silently mean something else

Small, but this class produced two of today's incidents: flags whose names promise one thing and
deliver another.

* `--skip-pdf` on `import-cmd` produced metadata-only records but printed `✅` (§5 evidence).
* `--limit` doubled as a work cap: a backfill silently wrote 20 of 1182 records and reported success.
* `hfpclawer fetch 2607.00287` wrote the PDF to `<repo>/pdfs/` while the store, the config and the
  audit all refer to `data/pdfs/` — **two directories now hold 62 PDFs between them** (11 vs 51).
  A record can therefore be "downloaded" and permanently invisible to any audit.
* `fetch` takes the arXiv id as a positional argument while `store ensure` takes `--aid`; a failed
  guess is caught only by Typer's error text.

**Structural fix.** A short "destructive/degrading flags" contract in `AGENTS.md`: any flag that
reduces fidelity must (a) print what it is *not* doing, (b) be recorded on the record it affects,
and (c) have a distinct work-cap flag where the default is "all". Path resolution should go through
one accessor, and the two PDF directories should be reconciled with a migration rather than left to
accumulate.

## 9. Priority if only three things get fixed

1. **Data invariants as a gate** (§5) — cheapest, and it converts every future finding from "an agent
   noticed" into "the release refused".
2. **Identifier events with method + similarity + actor** (§1) and a confidence gate on ingest (§1,
   §2) — this is what makes wrong attachments detectable at the point of entry rather than years
   later.
3. **Row-level mutation log + automatic pre-destructive export** (§6) — so cleanup is reversible by
   design and the audit can answer "what changed".

## 10. What should *not* be concluded from this pass

The data model was rich enough to *find* all of this: identifier types, venue, year, audit levels and
duplicate visibility were all present, and every defect was detected by comparing the store against
an external authority. The failures are in **provenance, invariants and audit trail** — the parts
that decide whether a stored fact can be trusted — not in the schema's expressiveness. A store that
mis-files 7% of its DOIs but records honestly where each one came from would be more useful than one
that files perfectly and cannot say why.

---

## 11. What v0.19.6 changed (status against this critique)

The critique is only worth writing if it changes the code. This section is the honest status: what
landed, what it caught on the way, and what is still open.

| § | Finding | Status in v0.19.6 |
|:--|:--|:--|
| §1 | Provenance is asserted, not recorded | **Partly fixed** — `store_events` records every identifier attach/remove with `method`, `confidence`, `actor`; the low-confidence band is now a reported finding. Per-field provenance (which *source* supplied each of title/venue/year) is still open. |
| §2 | The classifier cannot say "my evidence conflicts" | Open — the ordered rules are unchanged. The invariant now *reports* the cases that motivated the finding (`record.duplicate_identity`, `title.is_citation`), and `item_type` changes are logged with before/after so a wrong classification is traceable. |
| §3 | No uniqueness invariant on the identity reasoned over | **Fixed** — `identity_key` + `record.duplicate_identity` invariant + `store dedup` (dry run by default, snapshot first, verification before removal, `manual` verdict for same-work/different-artefact pairs). |
| §4 | The audit machine measures process, not evidence | Open — `audit_level` semantics unchanged; the coverage numbers (`year_coverage`, `with_identifier`) are now published by every `invariants` run, so a consumer can see how thin the audit actually is. |
| §5 | Green gates decoupled from the artifact | **Fixed** — `store invariants` is a real gate: deterministic, offline, per-check counts, `--strict`, `--json`, and a **ratchet baseline** that may only shrink. The release flow in `AGENTS.md` now includes it. |
| §6 | Data mutations had no audit trail | **Fixed** — `store_events` (migration v6) logs identifier add/remove/**transfer**, record removal (with a full row snapshot inside the event), `item_type` decisions and every pre-destructive snapshot; `store events` reads it; `store dedup` snapshots before writing. |
| §7 | Statistics on unmeasured label error | Open — the integrity numbers now exist per field and are printed by the gate; no analytical layer consumes them yet. |
| §8 | Semantics that silently mean something else | **Partly fixed** — one canonical `paths.pdf_dir()` (the two directories held 62 PDFs; now one, with the stray 11 moved), `--limit` vs `--max` separated, and `dedup` refuses to proceed when the move did not happen. Plumbed flag audits for other commands are still open. |

### What the new machinery caught within the hour

Three defects were found by the code written to find them, which is the whole argument for the gate:

1. **`identity_key` was designed wrong.** Keying on DOI → arXiv → title *cannot* find duplicates: the
   `UNIQUE(id_type, id_value)` constraint means two copies of one paper never share an identifier.
   The first test run failed and the design changed to title-first (§3).
2. **A merge built on `add_identifier` silently drops identifiers.** While the row still belongs to
   the source record, `INSERT OR IGNORE` on the target does nothing — the same failure that lost three
   arXiv ids during the manual cleanup. `transfer_identifier` (an `UPDATE`) is now the merge
   primitive, and `dedup` verifies every move before deleting anything.
3. **A test wrote the production baseline file.** The baseline used a global data directory, so a
   fixture store recorded a one-record baseline into the live `data/`. The baseline now lives beside
   the store it describes, which is both correct and test-safe.

### Still open (deliberately)

* Per-field provenance for metadata (`title_source`, `venue_source`, `year_source`).
* An evidence-aggregating classifier with an explicit `conflict` outcome (§2).
* Statistics that publish their own input error rate and refuse claims below a floor (§7).
* A flag-semantics contract in `AGENTS.md` for every flag that reduces fidelity (§8).
* The 58 findings recorded in the live baseline: 47 untitled records, 11 whose title is an
  identifier, 5 without any identifier, 5 non-paper DOI shapes, 2 citation-string titles. The ratchet
  records them; cleaning them is its own pass (they are data, not code).
