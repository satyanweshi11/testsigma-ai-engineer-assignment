"""Loads .env + config/target.yaml into one object the stages share."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"


@dataclass
class Settings:
    cfg: dict                       # parsed target.yaml
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    github_token: str | None

    @property
    def name(self) -> str:
        return self.cfg.get("name", "target")

    @property
    def artifacts_dir(self) -> Path:
        d = ARTIFACTS / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d


def load(config_path: str | Path = ROOT / "config" / "target.yaml") -> Settings:
    load_dotenv(ROOT / ".env")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return Settings(
        cfg=cfg,
        neo4j_uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.environ.get("NEO4J_USER", "neo4j"),
        neo4j_password=os.environ.get("NEO4J_PASSWORD", "testsigma123"),
        github_token=os.environ.get("GITHUB_TOKEN") or None,
    )
