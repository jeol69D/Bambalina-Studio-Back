from pathlib import Path
import json
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class SceneLine:
    speaker: str
    text: str
    animation: str = "Idle"
    expression: str = "neutral"
    duration: float = 3.0


@dataclass
class SceneMeta:
    title: str
    language: str
    humans: List[str]
    avatars: List[Dict[str, Any]]
    lipsync: str
    similarity_threshold: int


@dataclass
class Scene:
    meta: SceneMeta
    script: List[SceneLine]


def load_scene(path: Path) -> Scene:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = SceneMeta(**data["meta"])
    script = [SceneLine(**line) for line in data["script"]]
    return Scene(meta=meta, script=script)
