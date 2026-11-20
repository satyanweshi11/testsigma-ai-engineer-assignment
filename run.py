#!/usr/bin/env python3
"""Pipeline CLI. Each stage is independently runnable and writes to artifacts/,
so you can re-run any one stage without redoing the others.

    python run.py crawl      # Stage 1: capture UI  -> artifacts/<name>/ui.json
    python run.py ingest     # Stage 2: parse docs  -> artifacts/<name>/requirements.json
    python run.py codemap    # Stage 3: parse repo  -> artifacts/<name>/code.json
    python run.py link       # Stage 4: fuse layers -> artifacts/<name>/edges.json
    python run.py load       # Stage 5: -> Neo4j
    python run.py reason --pr <N>   # Stage 6: blast radius -> reports/
    python run.py all        # 1..5 in order
"""
from __future__ import annotations

import argparse
import sys

from src import config


def main() -> int:
    p = argparse.ArgumentParser(description="Blast Radius Engine")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("crawl")
    sub.add_parser("ingest")
    sub.add_parser("codemap")
    sub.add_parser("link")
    sub.add_parser("load")
    r = sub.add_parser("reason")
    r.add_argument("--pr", type=int, required=False)
    sub.add_parser("all")
    ch = sub.add_parser("chat")
    ch.add_argument("--port", type=int, default=8000)

    args = p.parse_args()
    settings = config.load()

    if args.cmd == "crawl":
        from src.crawl.crawler import run
        run(settings)
    elif args.cmd == "ingest":
        from src.ingest.requirements import run
        run(settings)
    elif args.cmd == "codemap":
        from src.codemap.mapper import run
        run(settings)
    elif args.cmd == "link":
        from src.link.linker import run
        run(settings)
    elif args.cmd == "load":
        from src.graph.loader import run
        run(settings)
    elif args.cmd == "reason":
        from src.reason.blast_radius import run
        run(settings, pr_number=args.pr)
    elif args.cmd == "chat":
        import uvicorn
        print(f"Blast Radius Assistant -> http://localhost:{args.port}")
        uvicorn.run("src.chat.server:app", host="127.0.0.1", port=args.port)
    elif args.cmd == "all":
        from src.codemap.mapper import run as codemap_run
        from src.ingest.requirements import run as ingest_run
        from src.crawl.crawler import run as crawl_run
        from src.link.linker import run as link_run
        from src.graph.loader import run as load_run
        crawl_run(settings)
        ingest_run(settings)
        codemap_run(settings)
        link_run(settings)
        load_run(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
