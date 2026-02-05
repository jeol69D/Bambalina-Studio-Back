# File: bambalina_studio/bambalina_core/director.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from difflib import SequenceMatcher

from .models import Line, normalize

# Preferencia de voz para actores virtuales (UI la rellena).
GenderPref = str  # "auto" | "f" | "m"


@dataclass
class EnsayoDirector:
    """
    Orquesta el ensayo: decide de quién es el turno, se valida líneas humanas
    por similitud y avanza el índice global del guion.

    Contratos:
    - La UI es la única responsable de locutor (TTS). Este director NO llama TTS,
      salvo vía `consume_virtuals()` si se le inyecta `tts` explícitamente.
    - `feed_transcript()` solo se valida y avanza cuando es turno humano.
    """

    script: List[Line]
    human_characters: Set[str]
    threshold: int = 70  # 0..100
    tts: Optional[object] = None  # TTSProvider opcional (solo para consume_virtuals)
    idx: int = 0

    # Mapeo de voz deseada por personaje virtual ("auto"|"f"|"m"), lo gestiona la UI.
    virtual_gender_pref: Dict[str, GenderPref] = field(default_factory=dict)

    # ---------- turnos ----------
    def is_human_turn(self) -> bool:
        if self.idx >= len(self.script):
            return False
        return self.script[self.idx].speaker in self.human_characters

    # ---------- avance por entrada humana ----------
    def feed_transcript(self, text: str) -> bool:
        """
        Intenta casar `text` con la línea humana actual.
        Si supera `threshold`, avanza `idx` y devuelve True.
        """
        if not text or self.idx >= len(self.script):
            return False
        if not self.is_human_turn():
            return False

        expected = self.script[self.idx].text
        sim = self._similarity(text, expected)
        if sim >= max(0, min(100, self.threshold)):
            self.idx += 1
            return True
        return False

    # ---------- consumo de virtuales (opcional) ----------
    def consume_virtuals(self) -> int:
        """
        Avanza por todas las líneas virtuales desde `idx` y (si hay `tts`)
        las locuta. Devuelve cuántas líneas virtuales se consumieron.
        """
        count = 0
        # Importante: no bloquear si no hay script restante.
        while self.idx < len(self.script) and not self.is_human_turn():
            line = self.script[self.idx]
            if self.tts is not None:
                pref = self.virtual_gender_pref.get(line.speaker, "auto")
                # type: ignore[attr-defined]  # Evita depender del tipo concreto
                self.tts.say(line.text, voice_pref=pref)  # noqa: B009
            self.idx += 1
            count += 1
        return count

    # ---------- navegación manual ----------
    def jump_next(self) -> None:
        if self.idx < len(self.script):
            self.idx += 1

    def jump_prev(self) -> None:
        if self.idx > 0:
            self.idx -= 1

    # ---------- UI helper ----------
    def next_prompt(self) -> str:
        if self.idx >= len(self.script):
            return "FIN DEL GUION"
        line = self.script[self.idx]
        if line.speaker in self.human_characters:
            return f"TU TURNO — {line.speaker}: {line.text}"
        return f"TURNO DE {line.speaker}: {line.text}"

    # ---------- util ----------
    @staticmethod
    def _similarity(a: str, b: str) -> int:
        """
        Similar 0..100 usando texto normalizado. Penaliza desorden menor.
        """
        na, nb = normalize(a), normalize(b)
        if not na or not nb:
            return 0
        # Ratio difflib es robusto para pequeñas variaciones.
        ratio = SequenceMatcher(None, na, nb).ratio()
        # Boost si es prefijo/sufijo (casos de lectura parcial correcta).
        if na in nb or nb in na:
            ratio = max(ratio, min(len(na), len(nb)) / max(len(na), len(nb)))
        return int(round(ratio * 100))
