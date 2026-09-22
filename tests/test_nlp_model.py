#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Model resolution for the lazy spaCy loader (hfpapers.nlp).

The `nlp` extra installs ``en_core_web_sm`` because PyPI refuses the direct-URL
wheel of ``en_core_web_md`` — the model the semantic paths prefer and the one
``python -m spacy download`` gives. The loader therefore has to accept either,
most capable first: asking for a single fixed name left NLP disabled on a
correctly installed extra (installed extra, no working model, warning nobody
expects).
"""

from __future__ import annotations

import logging
import sys
import types

import pytest


def _install_fake_spacy(monkeypatch, available: set[str]) -> list[str]:
    """Register a fake ``spacy`` module; return the list of names it was asked for."""
    calls: list[str] = []

    def load(name: str):
        calls.append(name)
        if name not in available:
            raise OSError(f"[E050] Can't find model '{name}'")
        return {"model": name}

    module = types.ModuleType("spacy")
    module.load = load  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "spacy", module)
    return calls


@pytest.fixture
def fresh_loader(monkeypatch):
    """Reset the loader's module state so each test starts from "nothing loaded"."""
    import hfpapers.nlp as nlp

    monkeypatch.setattr(nlp, "_NLP_INSTANCE", None)
    monkeypatch.setattr(nlp, "_SPACY_MODEL", None)
    monkeypatch.setattr(nlp, "_SPACY_WARNED", False)
    monkeypatch.setattr(nlp, "_MODEL_WARNED", False)
    return nlp


def test_falls_back_to_the_model_the_extra_installs(fresh_loader, monkeypatch):
    calls = _install_fake_spacy(monkeypatch, available={"en_core_web_sm"})

    nlp_obj = fresh_loader._load_spacy()

    assert nlp_obj == {"model": "en_core_web_sm"}
    assert calls == ["en_core_web_md", "en_core_web_sm"]  # preferred first, then real one
    assert fresh_loader._SPACY_MODEL == "en_core_web_sm"  # what actually loaded is recorded


def test_preferred_model_wins_when_both_are_present(fresh_loader, monkeypatch):
    calls = _install_fake_spacy(
        monkeypatch, available={"en_core_web_md", "en_core_web_sm"}
    )

    nlp_obj = fresh_loader._load_spacy()

    assert nlp_obj == {"model": "en_core_web_md"}
    assert calls == ["en_core_web_md"]  # no need to probe further


def test_configured_model_is_tried_first(fresh_loader, monkeypatch):
    calls = _install_fake_spacy(monkeypatch, available={"en_core_web_sm"})
    fresh_loader._SPACY_MODEL = "en_core_web_sm"

    assert fresh_loader._load_spacy() == {"model": "en_core_web_sm"}
    assert calls == ["en_core_web_sm"]


def test_no_model_available_warns_once_and_returns_none(fresh_loader, monkeypatch, caplog):
    calls = _install_fake_spacy(monkeypatch, available=set())

    with caplog.at_level(logging.WARNING, logger="hfpapers.nlp"):
        assert fresh_loader._load_spacy() is None
        assert fresh_loader._load_spacy() is None  # second call must not re-warn

    # Each call retries the candidates (nothing can be cached when none loads) —
    # what matters is that only the two known names are probed and the warning
    # is emitted once.
    assert calls[:2] == ["en_core_web_md", "en_core_web_sm"]
    assert set(calls) == {"en_core_web_md", "en_core_web_sm"}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "en_core_web_md" in warnings[0].getMessage()


def test_missing_spacy_warns_with_the_extra_to_install(fresh_loader, monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "spacy", None)  # `import spacy` → ImportError

    with caplog.at_level(logging.WARNING, logger="hfpapers.nlp"):
        assert fresh_loader._load_spacy() is None

    message = " ".join(r.getMessage() for r in caplog.records)
    assert "hfpclawer[nlp]" in message
