#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""semantic_service.py — Lightweight FastAPI semantic similarity sidecar.

Provides embedding and similarity endpoints using sentence-transformers.
Designed as a sidecar service for expflow: expflow calls HTTP, no torch dep.

Endpoints:
    POST /embed          — Compute embedding for a text
    POST /similarity     — Compute cosine similarity between two texts
    POST /classify       — Classify text against reference concepts
    GET  /health          — Health check

Hardware auto-detection via HardwareProbe: CUDA GPU if available, else CPU.
Model: all-MiniLM-L6-v2 (~80MB, fast CPU inference).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

# FastAPI imports (stdlib — no torch needed here, only in the model wrapper)
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

logger = logging.getLogger("semantic_service")

# ── Model config ──
_MODEL_NAME = os.environ.get(
    "SEMANTIC_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
# Support HF mirror endpoint for environments with restricted access
_HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "")
if _HF_ENDPOINT:
    os.environ["HF_ENDPOINT"] = _HF_ENDPOINT


app = FastAPI(
    title="semantic-service",
    description="Semantic similarity sidecar for expflow — sentence-transformers embeddings",
    version="0.1.0",
)

# ── Lazy-loaded model singleton ──

_model = None
_model_device = "cpu"


def _get_model():
    """Lazy-load sentence-transformers model (CPU safe)."""
    global _model, _model_device
    if _model is not None:
        return _model

    try:
        from hfpapers.hardware import HardwareProbe

        hw = HardwareProbe()
        device = "cuda" if hw.use_bert else "cpu"
    except Exception:
        device = "cpu"

    try:
        from sentence_transformers import SentenceTransformer

        model_name = _MODEL_NAME
        logger.info("Loading model %s on %s...", model_name, device)
        _model = SentenceTransformer(model_name, device=device)
        _model_device = device
        logger.info("Model loaded on %s", device)
        return _model
    except ImportError as e:
        raise RuntimeError(
            "sentence-transformers not installed. "
            "Run: pip install sentence-transformers"
        ) from e
    except Exception as e:
        raise RuntimeError(f"Failed to load model: {e}") from e


# ── Pydantic schemas ──


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    embedding: list[float]
    dimension: int
    device: str


class SimilarityRequest(BaseModel):
    text_a: str
    text_b: str


class SimilarityResponse(BaseModel):
    similarity: float
    device: str


class ClassifyRequest(BaseModel):
    text: str
    concepts: list[str]


class ClassifyResponse(BaseModel):
    scores: dict[str, float]
    top_concept: str
    top_score: float
    device: str


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    device: str
    message: str


# ── Endpoints ──


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check with model status."""
    loaded = _model is not None
    if loaded:
        device = _model_device
        msg = "Ready"
    else:
        device = "unknown"
        msg = "Model not loaded (call /embed or /similarity to trigger lazy load)"
    return HealthResponse(
        status="ok" if loaded else "degraded",
        model_loaded=loaded,
        device=device,
        message=msg,
    )


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest):
    """Compute embedding vector for a text."""
    try:
        model = _get_model()
        emb = model.encode(req.text, normalize_embeddings=True)
        return EmbedResponse(
            embedding=emb.tolist(),
            dimension=int(emb.shape[0]),
            device=_model_device,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/similarity", response_model=SimilarityResponse)
async def similarity(req: SimilarityRequest):
    """Compute cosine similarity between two texts."""
    try:
        model = _get_model()
        emb_a = model.encode(req.text_a, normalize_embeddings=True)
        emb_b = model.encode(req.text_b, normalize_embeddings=True)
        sim = float(np.dot(emb_a, emb_b))
        return SimilarityResponse(similarity=sim, device=_model_device)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/classify", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest):
    """Classify a text against a list of reference concepts.

    Returns cosine similarity scores for each concept and the best match.
    """
    try:
        model = _get_model()
        emb_text = model.encode(req.text, normalize_embeddings=True)
        emb_concepts = model.encode(req.concepts, normalize_embeddings=True)
        scores = {
            concept: float(np.dot(emb_text, emb_concept))
            for concept, emb_concept in zip(req.concepts, emb_concepts)
        }
        top_concept = max(scores, key=scores.get)
        return ClassifyResponse(
            scores=scores,
            top_concept=top_concept,
            top_score=scores[top_concept],
            device=_model_device,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── CLI entry point ──


def main():
    parser = argparse.ArgumentParser(
        description="Start semantic similarity sidecar service"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8765,
        help="Port (default: 8765)",
    )
    parser.add_argument(
        "--preload",
        action="store_true",
        help="Preload model on startup (otherwise loaded on first request)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging level",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.preload:
        logger.info("Preloading model...")
        try:
            _get_model()
            logger.info("Model preloaded on %s", _model_device)
        except RuntimeError as e:
            logger.error("Preload failed: %s", e)
            sys.exit(1)

    logger.info(
        "Starting semantic service on http://%s:%d", args.host, args.port
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
