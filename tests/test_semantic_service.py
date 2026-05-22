#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for semantic_service — FastAPI sidecar endpoints.

Uses TestClient (FastAPI's built-in test client).
Mocks sentence_transformers via sys.modules injection to avoid
import errors when sentence-transformers is not installed.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np

# ── Mock sentence_transformers before ANY test imports ──
_mock_st = MagicMock()
_mock_model = MagicMock()
# encode returns normalized vector; support both single-string and list-of-strings
_embedding = np.array([0.1, 0.2, 0.3])
# When called with a list, return a 2D array; when called with a string, return 1D
def _encode_side_effect(texts, **kwargs):
    if isinstance(texts, list):
        return np.tile(_embedding, (len(texts), 1))
    return _embedding
_mock_model.encode.side_effect = _encode_side_effect
_mock_model.get_sentence_embedding_dimension.return_value = 3
_mock_st.SentenceTransformer.return_value = _mock_model

# Namespace mock for sentence_transformers.backend and friends
_mock_st.backend = MagicMock()
_mock_st.backend.load = MagicMock()
_mock_st.util = MagicMock()
_mock_st.util.decorators = MagicMock()

sys.modules["sentence_transformers"] = _mock_st
sys.modules["sentence_transformers.backend"] = _mock_st.backend
sys.modules["sentence_transformers.backend.load"] = _mock_st.backend.load
sys.modules["sentence_transformers.util"] = _mock_st.util
sys.modules["sentence_transformers.util.decorators"] = _mock_st.util.decorators

from fastapi.testclient import TestClient

# Now safe to import app — sentence_transformers is already mocked
import hfpapers.semantic_service as svc

svc._model = _mock_model
svc._model_device = "cpu"


class TestSemanticService(unittest.TestCase):
    """Test FastAPI endpoints with mocked SentenceTransformer."""

    def setUp(self):
        self.client = TestClient(svc.app)

    # ── /health ──

    def test_health_returns_ok_when_model_loaded(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["model_loaded"])
        self.assertEqual(data["device"], "cpu")

    # ── /embed ──

    def test_embed_returns_embedding(self):
        resp = self.client.post("/embed", json={"text": "hello world"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("embedding", data)
        self.assertEqual(data["dimension"], 3)
        self.assertEqual(len(data["embedding"]), 3)
        self.assertEqual(data["device"], "cpu")

    def test_embed_empty_text(self):
        resp = self.client.post("/embed", json={"text": ""})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("embedding", data)

    def test_embed_missing_field(self):
        resp = self.client.post("/embed", json={})
        self.assertEqual(resp.status_code, 422)

    # ── /similarity ──

    def test_similarity_returns_score(self):
        resp = self.client.post(
            "/similarity", json={"text_a": "hello", "text_b": "world"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("similarity", data)
        # dot product of [0.1,0.2,0.3] with itself
        expected = 0.1 * 0.1 + 0.2 * 0.2 + 0.3 * 0.3
        self.assertAlmostEqual(data["similarity"], expected)

    def test_similarity_missing_fields(self):
        resp = self.client.post("/similarity", json={"text_a": "hello"})
        self.assertEqual(resp.status_code, 422)

    # ── /classify ──

    def test_classify_returns_scores(self):
        resp = self.client.post(
            "/classify",
            json={"text": "some text", "concepts": ["a", "b"]},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("scores", data)
        self.assertIn("top_concept", data)
        self.assertIn("top_score", data)
        self.assertIn(data["top_concept"], ["a", "b"])

    def test_classify_empty_concepts(self):
        resp = self.client.post(
            "/classify",
            json={"text": "some text", "concepts": [""]},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("scores", data)

    def test_classify_missing_list(self):
        resp = self.client.post("/classify", json={"text": "some text"})
        self.assertEqual(resp.status_code, 422)

    # ── bad requests ──

    def test_invalid_json_returns_422(self):
        resp = self.client.post(
            "/embed",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 422)
