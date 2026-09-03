"""Repo interest-profile tests (AGENTS.md hfpclawer block parsing)."""

from hfpapers.profile import detect_profile, find_agents_md, parse_agents_profile

AGENTS_WITH_PROFILE = """\
# demo repo — Agent Working Guide

## Context
Research topic notes...

## HFPCrawler Interest Profile

```yaml
hfpclawer:
  profile: demo-accelerator
  queries:
    - query: "plasma accelerator simulation"
      weight: 3
    - query: "laser wakefield"
      weight: 2
  categories: [plasma, accelerator]
  from_wiki: concepts/demo-page
```
"""

AGENTS_NO_PROFILE = """\
# plain repo

No hfpclawer block here.

```yaml
other:
  tool: x
```
"""

AGENTS_BROKEN_YAML = """\
# broken repo

```yaml
hfpclawer:
  queries: [
```
"""


def test_find_agents_walks_up(tmp_path):
    (tmp_path / "AGENTS.md").write_text(AGENTS_WITH_PROFILE)
    nested = tmp_path / "sub" / "deep"
    nested.mkdir(parents=True)
    found = find_agents_md(nested)
    assert found == tmp_path / "AGENTS.md"


def test_find_agents_from_file_path(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text(AGENTS_WITH_PROFILE)
    assert find_agents_md(p) == p


def test_find_agents_missing(tmp_path):
    assert find_agents_md(tmp_path) is None


def test_parse_profile_block(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text(AGENTS_WITH_PROFILE)
    prof = parse_agents_profile(p)
    assert prof.profile == "demo-accelerator"
    assert len(prof.queries) == 2
    assert prof.categories == ["plasma", "accelerator"]
    assert prof.from_wiki == "concepts/demo-page"
    tuples = prof.query_tuples()
    assert tuples == [
        ("plasma accelerator simulation", 3),
        ("laser wakefield", 2),
    ]


def test_parse_no_profile_block(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text(AGENTS_NO_PROFILE)
    prof = parse_agents_profile(p)
    assert prof.is_empty


def test_parse_broken_yaml_defensive(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text(AGENTS_BROKEN_YAML)
    prof = parse_agents_profile(p)
    # parse failure must never raise — empty profile, tooling unaffected
    assert prof.is_empty


def test_parse_missing_file(tmp_path):
    prof = parse_agents_profile(tmp_path / "nope.md")
    assert prof.is_empty


def test_detect_profile(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text(AGENTS_WITH_PROFILE)
    prof = detect_profile(tmp_path)
    assert prof.profile == "demo-accelerator"
    assert prof.agents_path == str(p)


def test_user_profile_loads(monkeypatch, tmp_path):
    import hfpapers.profile as mod

    home = tmp_path / "home"
    (home / ".hfpclawer").mkdir(parents=True)
    (home / ".hfpclawer" / "profile.yaml").write_text(
        "hfpclawer:\n  profile: machine-user\n"
        "  queries:\n    - query: stellarator\n      weight: 3\n"
        "  categories: [fusion]\n"
    )
    monkeypatch.setattr(mod, "user_profile_dir", lambda: home / ".hfpclawer")
    prof = mod.user_profile()
    assert prof.profile == "machine-user"
    assert prof.query_tuples() == [("stellarator", 3)]


def test_user_profile_absent(monkeypatch, tmp_path):
    import hfpapers.profile as mod

    monkeypatch.setattr(mod, "user_profile_dir", lambda: tmp_path / ".hfpclawer")
    prof = mod.user_profile()
    assert prof.is_empty
