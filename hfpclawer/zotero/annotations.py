#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""annotations.py — Extract PDF annotations via Zotero API + PyMuPDF.

Pure HTTP API + PDF parser pipeline. NO direct Zotero SQLite access.

Flow:
  1. Zotero API: resolve arXiv ID → parent item key → PDF attachment key → file path
  2. PyMuPDF: extract highlights/underlines from local PDF
  3. Format: render as Markdown or JSON

Usage:
    from hfpclawer.zotero.annotations import get_pdf_annotations

    anns = get_pdf_annotations(arxiv_id="1905.01522")
    print(format_markdown(anns))
"""

from __future__ import annotations

import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Optional

from hfpclawer.zotero import get_zotero_url, is_zotero_remote

logger = logging.getLogger("hfpclawer.zotero.annotations")


# ─── Color helpers ──────────────────────────────────

# PyMuPDF colors: (R, G, B) in [0, 1]
_PDF_COLOR_NAMES: dict[tuple[float, float, float], str] = {
    (1.0, 0.0, 0.0): "🔴 Red",
    (0.0, 1.0, 0.0): "🟢 Green",
    (0.0, 0.0, 1.0): "🔵 Blue",
    (1.0, 1.0, 0.0): "🟡 Yellow",
    (1.0, 0.647, 0.0): "🟠 Orange",
    (1.0, 0.412, 0.706): "🩷 Pink",
    (0.541, 0.169, 0.886): "🟣 Purple",
    (0.584, 0.584, 0.584): "⬜ Gray",
}


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    """Convert PDF RGB tuple to hex color string."""
    r = min(255, max(0, int(rgb[0] * 255)))
    g = min(255, max(0, int(rgb[1] * 255)))
    b = min(255, max(0, int(rgb[2] * 255)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _color_label(rgb: tuple[float, float, float]) -> str:
    """Get emoji + name for a PDF color, fallback to hex."""
    # Find closest named color
    key = (round(rgb[0], 3), round(rgb[1], 3), round(rgb[2], 3))
    best_name = _PDF_COLOR_NAMES.get(key)
    if best_name:
        return best_name
    return f"🎨 {_rgb_to_hex(rgb)}"


# ─── API helpers ────────────────────────────────────


def _api_url(path: str) -> str:
    """Build an absolute Zotero API URL.

    Args:
        path: API path with leading slash (e.g. '/items/ABC123').
    """
    base = get_zotero_url()
    return f"{base}/api/users/0{path}"


def _api_request(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    timeout: float = 15.0,
) -> Any:
    """Send an HTTP request to Zotero API.

    Auto-injects Host header spoofing when the configured Zotero is remote.
    """
    headers: dict[str, str] = {
        "User-Agent": "pyzotero/1.13.2",
        "Zotero-API-Version": "3",
    }
    if is_zotero_remote():
        headers["Host"] = "localhost:23119"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            import json
            return json.loads(raw)
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Cannot reach Zotero at {url}: {e.reason}. "
            "Ensure Zotero is running with local API enabled."
        ) from e


# ─── Public API ─────────────────────────────────────


def resolve_pdf_path(
    arxiv_id: str = "",
    zotero_key: str = "",
    title: str = "",
) -> dict:
    """Resolve a Zotero item to its local PDF file path.

    Args:
        arxiv_id: arXiv ID to look up (e.g., "1905.01522").
                  Mutually exclusive with zotero_key.
        zotero_key: Direct Zotero item key (e.g., "XVLZEDC4").
        title: Paper title (optional — enables fast keyword-search path).

    Returns:
        dict with:
          - "parent_key": Zotero item key
          - "pdf_path": absolute path to PDF file (str)
          - "title": paper title (str)
          - "error": error message if failed

    Raises:
        ConnectionError: If Zotero is unreachable.
    """
    # Step 1: resolve to parent key
    if arxiv_id:
        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        parent_key = zc.is_arxiv_in_zotero(arxiv_id, title=title)
        if not parent_key:
            return {"error": f"arXiv {arxiv_id} not found in Zotero"}
    elif zotero_key:
        parent_key = zotero_key
        # Verify it exists
        try:
            item = _api_request(_api_url(f"/items/{parent_key}"))
            if not item or not item.get("data"):
                return {"error": f"Zotero key '{zotero_key}' not found"}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"error": f"Zotero key '{zotero_key}' not found"}
            return {"error": f"Zotero API error: HTTP {e.code}"}
        except Exception:
            return {"error": "Zotero is not running"}
    else:
        return {"error": "Provide either arxiv_id or zotero_key"}

    # Step 2: get paper title
    try:
        item = _api_request(_api_url(f"/items/{parent_key}"))
    except ConnectionError:
        return {"error": "Zotero is not running"}
    title = (item.get("data", {}) or {}).get("title", "")

    # Step 3: find PDF attachment
    try:
        children = _api_request(_api_url(f"/items/{parent_key}/children"))
    except ConnectionError:
        return {"error": "Zotero is not running"}

    pdf_attachment = None
    for child in children:
        cdata = child.get("data", {})
        if cdata.get("itemType") == "attachment" and (
            cdata.get("contentType") == "application/pdf"
            or (cdata.get("filename") or "").lower().endswith(".pdf")
        ):
            pdf_attachment = cdata
            break

    if not pdf_attachment:
        return {"error": f"No PDF attachment found for {parent_key}"}

    attach_key = pdf_attachment.get("key", "")
    if not attach_key:
        return {"error": "PDF attachment has no key"}

    # Step 4: get local file path
    try:
        file_url = _api_url(f"/items/{attach_key}/file/view/url")
        headers: dict[str, str] = {}
        if is_zotero_remote():
            headers["Host"] = "localhost:23119"
        req = urllib.request.Request(file_url, method="GET", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            file_url_str = resp.read().decode("utf-8").strip()
    except urllib.error.HTTPError as e:
        if e.code == 302:
            # Redirect response — extract Location header
            loc = e.headers.get("Location", "")
            file_url_str = loc if loc else f"Redirect {e.code}"
        else:
            return {"error": f"File URL failed: HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"error": f"File URL failed: {e.reason}"}

    # Convert file:// URL to path
    if file_url_str.startswith("file://"):
        local_path = file_url_str[7:]  # strip file://
    else:
        local_path = file_url_str

    # Handle URL encoding in path
    from urllib.parse import unquote
    local_path = unquote(local_path)

    # Verify file exists
    path_obj = Path(local_path)
    if not path_obj.exists():
        return {
            "error": (
                f"PDF file not found at: {local_path}\n"
                "The PDF may be linked (imported_url mode) and not stored locally. "
                "Annotations can only be extracted from locally stored PDFs."
            ),
            "pdf_path": local_path,
            "parent_key": parent_key,
            "title": title,
        }

    return {
        "parent_key": parent_key,
        "pdf_path": str(path_obj.resolve()),
        "title": title,
    }


def extract_pdf_annotations(pdf_path: str) -> list[dict]:
    """Extract annotations from a PDF file using PyMuPDF.

    Args:
        pdf_path: Absolute path to the PDF file.

    Returns:
        List of annotation dicts, each with:
          - page (int): 1-indexed page number
          - type (str): "highlight" | "underline" | "strikeout" | etc.
          - text (str): The highlighted/underlined text
          - comment (str): User's annotation comment (may be empty)
          - color (str): Hex color string (e.g., "#ffd400")
          - color_label (str): Human-readable color with emoji
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF not installed. Run: uv add pymupdf")
        return []

    doc = fitz.open(pdf_path)
    results: list[dict] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        annots = list(page.annots())
        if not annots:
            continue

        for ann in annots:
            ann_type_num = ann.type[0]
            ann_type_name = ann.type[1]

            # Only extract visual mark annotations (highlights, underlines, etc.)
            # 8=Highlight, 9=Underline, 10=StrikeOut, 11=Squiggly
            if ann_type_num not in (8, 9, 10, 11):
                continue

            # Extract the text covered by the annotation
            text = ""
            # Try QuadPoints first (more precise for multi-line highlights)
            quads = getattr(ann, "quad_points", None)
            if quads:
                # Each quad is a tuple of 4 Point objects
                # Merge all quads' text
                segments = []
                for quad in quads:
                    # Build rect from quad points
                    x0 = min(p.x for p in quad)
                    y0 = min(p.y for p in quad)
                    x1 = max(p.x for p in quad)
                    y1 = max(p.y for p in quad)
                    q_rect = fitz.Rect(x0, y0, x1, y1)
                    seg = page.get_textbox(q_rect).strip()
                    if seg:
                        segments.append(seg)
                text = " ".join(segments)
            else:
                # Fallback to annotation bounding rect
                text = page.get_textbox(ann.rect).strip()

            # Get comment/note from annotation info
            info = ann.info
            comment = info.get("content", "") or ""

            # Get color
            color_rgb = ann.colors.get("stroke")
            if color_rgb:
                hex_color = _rgb_to_hex(tuple(color_rgb))
                color_label = _color_label(tuple(color_rgb))
            else:
                hex_color = ""
                color_label = ""

            results.append({
                "page": page_num + 1,
                "type": ann_type_name.lower(),
                "text": text,
                "comment": comment,
                "color": hex_color,
                "color_label": color_label,
            })

    doc.close()
    return results


def format_markdown(
    anns: list[dict],
    title: str = "",
    parent_key: str = "",
) -> str:
    """Format annotations as readable Markdown.

    Args:
        anns: List of annotation dicts from extract_pdf_annotations().
        title: Paper title for the heading.
        parent_key: Zotero item key for reference.

    Returns:
        Markdown string.
    """
    if not anns:
        return "*No annotations found.*\n"

    lines: list[str] = []
    if title:
        lines.append(f"## 🖍️ Annotations: {title}")
    else:
        lines.append("## 🖍️ PDF Annotations")
    if parent_key:
        lines.append(f"*Zotero: `{parent_key}`*\n")
    else:
        lines.append("")

    for i, ann in enumerate(anns, 1):
        page = ann.get("page", "?")
        atype = ann.get("type", "highlight")
        color_label = ann.get("color_label", "")
        text = ann.get("text", "")
        comment = ann.get("comment", "")

        # Type icon
        type_icon = {
            "highlight": "🖍️",
            "underline": "＿",
            "strikeout": "~~",
            "squiggly": "﹏",
        }.get(atype, "📌")

        lines.append(f"### {type_icon} {i}. p.{page} {color_label}")
        if text:
            lines.append(f"> {text}")
        if comment:
            lines.append(f"\n- *注解：{comment}*")
        lines.append("")

    return "\n".join(lines)


def format_json(anns: list[dict]) -> str:
    """Format annotations as pretty-printed JSON."""
    import json
    return json.dumps(anns, ensure_ascii=False, indent=2)


def get_pdf_annotations(
    arxiv_id: str = "",
    zotero_key: str = "",
) -> dict:
    """High-level entry point: resolve a paper and extract its PDF annotations.

    Args:
        arxiv_id: arXiv ID to look up.
        zotero_key: Direct Zotero item key.

    Returns:
        dict with:
          - "annotations": list of annotation dicts
          - "title": paper title
          - "parent_key": Zotero item key
          - "error": error message if any step failed
    """
    # Step 1: resolve PDF path
    info = resolve_pdf_path(arxiv_id=arxiv_id, zotero_key=zotero_key)
    if "error" in info:
        return {"error": info["error"]}

    pdf_path = info["pdf_path"]
    title = info.get("title", "")
    parent_key = info.get("parent_key", "")

    # Step 2: verify PDF exists
    if not Path(pdf_path).exists():
        return {
            "error": f"PDF not found: {pdf_path}",
            "title": title,
            "parent_key": parent_key,
        }

    # Step 3: extract annotations
    anns = extract_pdf_annotations(pdf_path)

    return {
        "annotations": anns,
        "title": title,
        "parent_key": parent_key,
    }


def color_filter(
    anns: list[dict],
    color_hex: str = "",
    color_name: str = "",
) -> list[dict]:
    """Filter annotations by color.

    Args:
        anns: List of annotation dicts.
        color_hex: Filter by hex color (e.g., "#ffd400").
        color_name: Filter by color name substring (e.g., "Yellow").

    Returns:
        Filtered list.
    """
    if not color_hex and not color_name:
        return anns

    filtered = []
    for ann in anns:
        hex_ok = not color_hex or ann.get("color", "").lower() == color_hex.lower()
        name_ok = not color_name or color_name.lower() in ann.get("color_label", "").lower()
        if hex_ok and name_ok:  # AND — both filters must pass when both are set
            filtered.append(ann)
    return filtered
