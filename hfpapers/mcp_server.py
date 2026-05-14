#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── MCP Server ──────────────────────────────
# hfpapers/mcp_server.py
# Hermes Agent / OpenCode remotely invoke crawler functions via MCP
# Standard input/output (stdio) mode — native integration

"""
MCP Tool List:
  hfpclawer_search    — Search new papers
  hfpclawer_download  — Download specified paper PDFs
  hfpclawer_convert   — Convert PDF→Markdown
  hfpclawer_info      — Lookup paper details
  hfpclawer_list      — List crawled papers
  hfpclawer_stats     — Crawler statistics
  hfpclawer_full      — Full pipeline
"""

import json
import logging
import sys

logger = logging.getLogger("hfpapers.mcp")


# Tool definitions (MCP JSON Schema)
MCP_TOOLS = {
    "hfpclawer_search": {
        "name": "hfpclawer_search",
        "description": "Search HF Papers for PDE/neural operator/physics-informed related papers, return new candidate papers",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_pages": {
                    "type": "integer",
                    "default": 2,
                    "description": "Pages per dimension",
                },
                "threshold": {
                    "type": "integer",
                    "default": 30,
                    "description": "Relevance threshold 0-100",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Display only, don't save",
                },
            },
        },
    },
    "hfpclawer_download": {
        "name": "hfpclawer_download",
        "description": "Download candidate paper PDFs",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10, "description": "Max PDFs to download"},
            },
        },
    },
    "hfpclawer_convert": {
        "name": "hfpclawer_convert",
        "description": "pymupdf4llm convert PDF to Markdown",
        "input_schema": {"type": "object", "properties": {}},
    },
    "hfpclawer_info": {
        "name": "hfpclawer_info",
        "description": "Query single paper details",
        "input_schema": {
            "type": "object",
            "properties": {
                "arxiv_id": {"type": "string", "description": "arXiv ID (e.g. 2509.05117)"},
            },
            "required": ["arxiv_id"],
        },
    },
    "hfpclawer_list": {
        "name": "hfpclawer_list",
        "description": "List crawled papers",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "Display count"},
            },
        },
    },
    "hfpclawer_stats": {
        "name": "hfpclawer_stats",
        "description": "Crawler statistics",
        "input_schema": {"type": "object", "properties": {}},
    },
    "hfpclawer_full": {
        "name": "hfpclawer_full",
        "description": "Full pipeline: search → download → convert",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_pages": {"type": "integer", "default": 2},
                "threshold": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
}


def _handle_search(args: dict) -> str:
    from hfpapers.evolved import DedupEngine, HFPapersCrawler, RelevanceDetector

    dedup = DedupEngine()
    detector = RelevanceDetector()
    clawler = HFPapersCrawler(dedup=dedup, detector=detector)
    papers = clawler.crawl(max_pages=args.get("max_pages", 2))
    papers = [p for p in papers if p.relevance >= args.get("threshold", 30)]

    result = {
        "total_new": len(papers),
        "papers": [
            {
                "arxiv_id": p.arxiv_id,
                "title": p.title[:120],
                "relevance": p.relevance,
                "category": p.categories[0] if p.categories else "",
                "code_url": p.code_url,
            }
            for p in papers
        ],
    }

    if not args.get("dry_run") and papers:
        from hfpapers.evolved import save_candidates

        save_candidates(papers)

    return json.dumps(result, indent=2, ensure_ascii=False)


def _handle_download(args: dict) -> str:
    from hfpapers.evolved import DedupEngine, PaperDownloader, load_candidates

    dedup = DedupEngine()
    downloader = PaperDownloader(dedup=dedup)
    candidates = load_candidates()
    if not candidates:
        return json.dumps({"error": "No candidate list"})
    papers = candidates[: args.get("limit", 10)]
    downloader.download_batch(papers)
    return json.dumps({"downloaded": len(papers)})


def _handle_convert(args: dict) -> str:
    from hfpapers.evolved import convert_pdfs

    count = convert_pdfs()
    return json.dumps({"converted": count})


def _handle_info(args: dict) -> str:
    import json as j
    import os

    from hfpapers.config import get as cfg_get

    dedup_path = os.path.expanduser(cfg_get("paths.global_dedup"))
    with open(dedup_path) as f:
        data = j.load(f)
    p = data.get("papers", {}).get(args["arxiv_id"])
    if not p:
        return j.dumps({"error": f"{args['arxiv_id']} not found"})
    return j.dumps(p, indent=2, ensure_ascii=False)


def _handle_list(args: dict) -> str:
    import json as j
    import os

    from hfpapers.config import get as cfg_get

    dedup_path = os.path.expanduser(cfg_get("paths.global_dedup"))
    with open(dedup_path) as f:
        data = j.load(f)
    papers = data.get("papers", {})
    limit = args.get("limit", 20)
    items = list(papers.items())[-limit:]
    return j.dumps(
        {
            "total": len(papers),
            "papers": [{"arxiv_id": k, "title": v.get("title", "")} for k, v in items],
        },
        indent=2,
        ensure_ascii=False,
    )


def _handle_stats(args: dict) -> str:
    import json as j
    import os

    from hfpapers.config import get as cfg_get

    dedup_path = os.path.expanduser(cfg_get("paths.global_dedup"))
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_dir = os.path.join(base, cfg_get("paths.pdf_dir", "pdfs"))
    md_dir = os.path.join(base, cfg_get("paths.md_dir", "mds"))

    with open(dedup_path) as f:
        data = j.load(f)
    pdf_count = (
        len([f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]) if os.path.isdir(pdf_dir) else 0
    )
    md_count = (
        len([f for f in os.listdir(md_dir) if f.endswith(".md")]) if os.path.isdir(md_dir) else 0
    )

    return j.dumps(
        {
            "total_papers": len(data.get("papers", {})),
            "pdf_files": pdf_count,
            "md_files": md_count,
            "crawl_date": data.get("crawl_date", ""),
        },
        indent=2,
        ensure_ascii=False,
    )


def _handle_full(args: dict) -> str:
    r1 = _handle_search(
        {
            "max_pages": args.get("max_pages", 2),
            "threshold": args.get("threshold", 30),
            "dry_run": False,
        }
    )
    r2 = _handle_download({"limit": args.get("limit", 10)})
    r3 = _handle_convert({})
    return json.dumps(
        {"search": json.loads(r1), "download": json.loads(r2), "convert": json.loads(r3)},
        indent=2,
        ensure_ascii=False,
    )


HANDLERS = {
    "hfpclawer_search": _handle_search,
    "hfpclawer_download": _handle_download,
    "hfpclawer_convert": _handle_convert,
    "hfpclawer_info": _handle_info,
    "hfpclawer_list": _handle_list,
    "hfpclawer_stats": _handle_stats,
    "hfpclawer_full": _handle_full,
}


def run_mcp_server(host: str = "127.0.0.1", port: int = 8765, mode: str = "stdio"):
    """Start MCP Server — supports stdio and HTTP modes

    stdio mode: For Hermes Agent native MCP client integration
    http mode: For OpenCode subagent subprocess calls or debugging
    """
    if mode == "stdio":
        _run_stdio()
    else:
        _run_http(host, port)


def _run_stdio():
    """stdio mode — Standard MCP JSON-RPC protocol

    Supports Hermes Agent native MCP client integration:
      - tools/list → Returns tool list
      - tools/call → Executes a tool
    """

    def respond(req_id, result=None, error=None):
        resp = {"jsonrpc": "2.0", "id": req_id}
        if error:
            resp["error"] = {"code": -32603, "message": str(error)}
        else:
            resp["result"] = result
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

    # First output full tool schema for tools/list
    # Subsequent requests read line by line from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id", 0)
            method = req.get("method", "")

            if method == "tools/list":
                respond(req_id, {"tools": list(MCP_TOOLS.values())})

            elif method == "tools/call":
                params = req.get("params", {})
                name = params.get("name", "")
                arguments = params.get("arguments", {})
                handler = HANDLERS.get(name)
                if handler:
                    result = handler(arguments)
                    respond(req_id, {"content": [{"type": "text", "text": str(result)}]})
                else:
                    respond(req_id, error=f"unknown tool: {name}")

            elif method == "initialize":
                respond(
                    req_id,
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "hfpapers-mcp", "version": "0.3.0"},
                    },
                )

            elif method == "notifications/initialized":
                respond(req_id, {})

            else:
                respond(req_id, error=f"unknown method: {method}")

        except json.JSONDecodeError:
            # Compatible with legacy line-JSON protocol
            try:
                req = json.loads(line)
                name = req.get("tool", req.get("name", ""))
                params = req.get("params", req.get("arguments", {}))
                handler = HANDLERS.get(name)
                if handler:
                    result = handler(params)
                else:
                    result = json.dumps({"error": f"unknown tool: {name}"})
                sys.stdout.write(str(result) + "\n")
                sys.stdout.flush()
            except Exception as e:
                logger.warning(f"_run_stdio: invalid input: {e}")
        except Exception as e:
            respond(req_id, error=str(e))


def _run_http(host: str, port: int):
    """HTTP mode — Hermes Agent invokes via REST API"""
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer
    except ImportError:
        logger.error("http.server not available")
        return

    class MCPHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/tools":
                self._respond(200, MCP_TOOLS)
            elif self.path.startswith("/call/"):
                tool_name = self.path[6:]
                handler = HANDLERS.get(tool_name)
                if not handler:
                    self._respond(404, {"error": f"unknown: {tool_name}"})
                    return
                result = handler({})
                self._respond(200, json.loads(result))
            elif self.path == "/health":
                self._respond(200, {"status": "ok"})
            else:
                self._respond(404, {"error": "not found"})

        def do_POST(self):
            if self.path.startswith("/call/"):
                tool_name = self.path[6:]
                handler = HANDLERS.get(tool_name)
                if not handler:
                    self._respond(404, {"error": f"unknown: {tool_name}"})
                    return
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b"{}"
                try:
                    params = json.loads(body)
                except json.JSONDecodeError:
                    params = {}
                result = handler(params)
                self._respond(200, json.loads(result))

        def _respond(self, code: int, data: dict):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def log_message(self, format, *args):
            logger.debug(format % args)

    server = HTTPServer((host, port), MCPHandler)
    logger.info(f"MCP HTTP Server @ http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
