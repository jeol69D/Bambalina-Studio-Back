# File: bambalina_studio/bambalina_core/models.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

import re

__all__ = [
    "Line",
    "normalize",
    "load_script",
    "list_speakers",
]

# Por qué: mantener tildes/ñ; quitar solo puntuación/símbolos.
# Conserva letras (incluidas con tildes), dígitos y espacios.
_CLEAN_RE = re.compile(r"[^0-9a-záéíóúüñ\s]", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Line:
    """Línea del guion."""
    speaker: str
    text: str


def normalize(s: str) -> str:
    """
    Normaliza para comparación/similitud:
    - casefold (minúsculas robustas)
    - elimina puntuación/símbolos (mantiene tildes/ñ)
    - colapsa espacios
    """
    if not s:
        return ""
    t = s.casefold()
    t = _CLEAN_RE.sub(" ", t)
    t = _SPACE_RE.sub(" ", t).strip()
    return t


def _parse_line(raw: str) -> Line:
    """
    Parsea una línea del archivo.
    Formato preferido: 'SPEAKER: texto'. Si no hay ':', se asigna a NARRADOR.
    """
    raw = raw.strip()
    if not raw:
        return Line("NARRADOR", "")  # descartable al final

    # Split solo en el primer ':'
    if ":" in raw:
        speaker, text = raw.split(":", 1)
        speaker = speaker.strip().upper()
        text = text.strip()
        # Por qué: si 'speaker:' sin texto, mantener para coherencia de índice.
        return Line(speaker or "NARRADOR", text)
    else:
        # Sin prefijo → narración
        return Line("NARRADOR", raw)


def load_script(path: str | Path) -> List[Line]:
    """
    Carga un guion de texto:
    - Codificación: UTF-8.
    - Líneas vacías se descartan.
    - Sin ':' → se asigna a NARRADOR.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe el archivo: {p}")

    data = p.read_text(encoding="utf-8", errors="replace")
    lines: List[Line] = []
    for raw in data.splitlines():
        ln = _parse_line(raw)
        # Descarta líneas sin contenido de texto si también son narrador vacío.
        if ln.text == "" and ln.speaker == "NARRADOR":
            continue
        lines.append(ln)

    if not lines:
        raise ValueError("El guion está vacío o no tiene líneas válidas.")
    return lines


def list_speakers(lines: Sequence[Line]) -> List[str]:
    """
    Lista de personajes únicos en orden de aparición.
    Incluye NARRADOR si existe.
    """
    seen: set[str] = set()
    ordered: List[str] = []
    for ln in lines:
        spk = ln.speaker
        if spk not in seen:
            seen.add(spk)
            ordered.append(spk)
    return ordered
