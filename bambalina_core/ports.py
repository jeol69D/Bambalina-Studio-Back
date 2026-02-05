from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional

class STTProvider(ABC):
    """Convierte audio en texto (streaming)."""
    @abstractmethod
    def start(self) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def listen_text(self, timeout: float = 0.8) -> str: ...

class TTSProvider(ABC):
    """Lee texto en voz."""
    @abstractmethod
    def say(self, text: str) -> None: ...

class CommandRecognizer(ABC):
    """Detecta comandos de control (p. ej., con 'wake word')."""
    @abstractmethod
    def detect(self, text: str) -> Optional[str]: ...
