"""Stage 3 — Code layer.

Clones the target repo (shallow) and extracts a code map: symbols (components,
functions, actions) with file+line, plus a file-level import/dependency graph.

Deliberately heuristic (regex over TS/TSX), not a type-aware AST. For mapping
named React components to the UI, component/function/action *names* are what the
linker needs, and names are cheap to extract reliably. The scope note in the design
doc defends this: a full TypeScript program analysis is the "another week" upgrade.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

from src.config import ROOT, Settings
from src.common.models import CodeSymbol, Edge

REPOS_DIR = ROOT / "repos"

# export const Foo = ... | export function Foo( | export default function Foo(
_EXPORT_FN = re.compile(
    r"^export\s+(?:default\s+)?(?:const|function|let)\s+([A-Za-z_]\w*)", re.M
)
# plain (non-exported) top-level function/const components too
_TOP_FN = re.compile(r"^(?:const|function)\s+([A-Za-z_]\w*)\s*[=(]", re.M)
# relative imports: import ... from "./x" / "../y"
_IMPORT = re.compile(r"""from\s+['"](\.[^'"]+)['"]""")


def clone_or_update(repo: str, ref: str) -> Path:
    """Shallow-clone owner/name at ref into repos/. Reuses an existing clone."""
    dest = REPOS_DIR / repo.replace("/", "__")
    if dest.exists():
        print(f"  reusing clone at {dest}")
        return dest
    REPOS_DIR.mkdir(exist_ok=True)
    url = f"https://github.com/{repo}.git"
    print(f"  cloning {url} ({ref}, depth 1) ...")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, "--single-branch", url, str(dest)],
        check=True,
    )
    return dest


def _iter_files(root: Path, includes: list[str], excludes: list[str]):
    seen: set[Path] = set()
    for pat in includes:
        for p in root.glob(pat):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if any(p.match(ex) or Path(rel).match(ex) for ex in excludes):
                continue
            if p in seen:
                continue
            seen.add(p)
            yield p


def _symbol_kind(rel_path: str, name: str) -> str:
    if "/actions/" in rel_path:
        return "action"
    if name[0].isupper():
        return "component"      # React component convention
    return "function"


def _resolve_import(from_file: Path, spec: str, root: Path) -> str | None:
    """Resolve a relative import spec to a repo-relative file path (best effort)."""
    base = (from_file.parent / spec).resolve()
    for cand in (
        base,
        base.with_suffix(".tsx"),
        base.with_suffix(".ts"),
        base / "index.tsx",
        base / "index.ts",
    ):
        if cand.exists() and cand.is_file():
            try:
                return cand.relative_to(root).as_posix()
            except ValueError:
                return None
    return None


def run(settings: Settings) -> None:
    code_cfg = settings.cfg["code"]
    repo = code_cfg["repo"]
    root = clone_or_update(repo, code_cfg.get("clone_ref", "main"))

    includes = code_cfg.get("include_globs", ["**/*.ts", "**/*.tsx"])
    excludes = code_cfg.get("exclude_globs", [])

    symbols: list[CodeSymbol] = []
    edges: list[Edge] = []
    files_seen: list[str] = []

    for f in _iter_files(root, includes, excludes):
        rel = f.relative_to(root).as_posix()
        files_seen.append(rel)
        text = f.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()

        # file-level symbol (import graph node + coarse mapping target)
        file_id = f"{rel}"
        symbols.append(
            CodeSymbol(id=file_id, kind="file", name=Path(rel).stem, path=rel,
                       repo=repo, start_line=1, end_line=len(lines))
        )

        # named symbols
        found: set[str] = set()
        for rx in (_EXPORT_FN, _TOP_FN):
            for m in rx.finditer(text):
                name = m.group(1)
                if name in found or name in {"default"}:
                    continue
                found.add(name)
                line_no = text[: m.start()].count("\n") + 1
                symbols.append(
                    CodeSymbol(
                        id=f"{rel}::{name}",
                        kind=_symbol_kind(rel, name),
                        name=name, path=rel, repo=repo, start_line=line_no,
                    )
                )

        # import edges (file -> file), relative only
        for m in _IMPORT.finditer(text):
            target = _resolve_import(f, m.group(1), root)
            if target:
                edges.append(Edge(src=file_id, dst=target, rel="DEPENDS_ON",
                                  confidence=1.0, evidence="import"))

    out = settings.artifacts_dir / "code.json"
    payload = {
        "repo": repo,
        "ref": code_cfg.get("clone_ref"),
        "n_files": len(files_seen),
        "symbols": [asdict(s) for s in symbols],
        "edges": [asdict(e) for e in edges],
    }
    out.write_text(json.dumps(payload, indent=2))
    n_comp = sum(1 for s in symbols if s.kind == "component")
    print(f"✓ codemap: {len(files_seen)} files, {len(symbols)} symbols "
          f"({n_comp} components), {len(edges)} import edges -> {out}")


if __name__ == "__main__":
    from src import config
    run(config.load())
