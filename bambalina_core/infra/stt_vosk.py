# File: bambalina_studio/infra/stt_vosk.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import json
import queue
import threading
import time
import logging

# Import tardío mejora mensajes de error; aquí directo para claridad.
import sounddevice as sd  # type: ignore
import vosk  # type: ignore

from bambalina_core.models import normalize


logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class STTConfig:
    device: Optional[int] = None
    samplerate: Optional[int] = None  # None => autodetect
    channels: int = 1                 # Vosk espera mono
    dtype: str = "int16"              # Raw bytes para menor GC
    log_level: int = -1               # silenciar Vosk por defecto


def _pick_samplerate(device: Optional[int], forced: Optional[int]) -> int:
    if forced:
        return int(forced)
    try:
        info = sd.query_devices(device, "input")
        sr = int(info["default_samplerate"])
        return sr if sr > 0 else 16000
    except Exception:
        return 16000


class VoskSTT:
    """
    Reconocimiento offline con Vosk.
    Interfaz: start()/pause()/resume()/stop() y read(timeout)->str|None.
    Cierra el micrófono en pause() para evitar ducking del sistema durante TTS.
    """

    def __init__(self, model_path: Path | str | None, config: Optional[STTConfig] = None) -> None:
        if model_path is None:
            model_path = Path(__file__).resolve().parents[1] / "models" / "vosk" / "es"

        self._model_path = Path(model_path)
        if not self._model_path.exists():
            raise FileNotFoundError(f"VoskSTT: modelo no encontrado: {self._model_path}")

        required = ["am", "conf", "graph"]
        missing = [r for r in required if not (self._model_path / r).exists()]
        if missing:
            raise FileNotFoundError(
                f"VoskSTT: modelo inválido en {self._model_path}, faltan carpetas: {', '.join(missing)}"
            )

        self._cfg = config or STTConfig()
        vosk.SetLogLevel(self._cfg.log_level)

        self._model: Optional[vosk.Model] = None  # type: ignore
        self._rec: Optional[vosk.KaldiRecognizer] = None  # type: ignore
        self._stream: Optional[sd.RawInputStream] = None

        self._q: "queue.Queue[bytes]" = queue.Queue(maxsize=16)
        self._running = False
        self._paused = False
        self._lock = threading.RLock()

        self._samplerate: int = 16000
        self._last_status: Optional[str] = None

    # ---------------- ciclo de vida ----------------
    def start(self) -> None:
        """Carga modelo, crea recognizer y abre stream de audio."""
        with self._lock:
            if self._running:
                logger.debug("VoskSTT.start(): ya corriendo")
                return

            self._samplerate = _pick_samplerate(self._cfg.device, self._cfg.samplerate)
            logger.info("VoskSTT.start(): samplerate=%s device=%s", self._samplerate, self._cfg.device)

            if self._model is None:
                self._model = vosk.Model(str(self._model_path))
                logger.info("VoskSTT: modelo cargado")

            #self._rec = vosk.KaldiRecognizer(self._model, float(self._samplerate))
            self._rec = vosk.KaldiRecognizer(self._model, 16000)
            self._running = True
            self._paused = False
            self._open_stream()
            self._drain_queue()  # limpio por si quedó audio viejo

    def pause(self) -> None:
        """Pausa captura cerrando el stream de micrófono (evita ducking)."""
        with self._lock:
            if not self._running or self._paused:
                return
            self._paused = True
            self._close_stream()
            self._drain_queue()
            logger.info("VoskSTT.pause(): stream cerrado y cola vaciada")

    def resume(self) -> None:
        """Reanuda captura reabriendo el stream de micrófono."""
        with self._lock:
            if not self._running or not self._paused:
                return
            self._open_stream()
            self._paused = False
            logger.info("VoskSTT.resume(): stream reabierto")

    def stop(self) -> None:
        """Detiene y libera recursos (stream/recognizer/model)."""
        with self._lock:
            if not self._running and self._stream is None and self._rec is None and self._model is None:
                return
            self._running = False
            self._paused = False
            self._close_stream()
            self._drain_queue()
            self._rec = None
            self._model = None
            logger.info("VoskSTT.stop(): recursos liberados")

    # ---------------- lectura ----------------
    def read(self, timeout: float = 0.1) -> Optional[str]:
        """
        Lee texto reconocido. Devuelve solo resultados *finales* (AcceptWaveform).
        Retorna None si no hay nada listo dentro del timeout.
        """
        # Evita trabajo si está pausado o sin recursos.
        if not self._running or self._paused or not self._rec or not self._stream:
            return None

        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            try:
                chunk = self._q.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                return None

            if not chunk:
                continue

            try:
                accepted = self._rec.AcceptWaveform(chunk)
            except Exception:
                # Si entra audio con formato inesperado, descártalo.
                continue

            if accepted:
                try:
                    res = json.loads(self._rec.Result())
                except Exception:
                    continue
                text = (res.get("text") or "").strip()
                if text and len(normalize(text)) >= 2:
                    logger.debug("VoskSTT.read(): texto final=%r", text)
                    return text
            # Ignoramos parciales.

        return None

    # ---------------- util ----------------
    def _open_stream(self) -> None:
        """Abre el stream de entrada si no existe; idempotente."""
        if self._stream is not None:
            return

        def _cb(indata, frames, time_info, status):
            # Callback ligero: solo encola bytes.
            if status:
                self._last_status = str(status)
            try:
                self._q.put_nowait(bytes(indata))
            except queue.Full:
                # Preferimos tirar audio a bloquear.
                pass

        try:
            self._stream = sd.RawInputStream(
                #samplerate=self._samplerate,
                samplerate=16000,
                blocksize=int(self._samplerate / 10),  # ~100ms
                device=self._cfg.device,
                channels=self._cfg.channels,
                dtype=self._cfg.dtype,
                callback=_cb,
            )
            self._stream.start()
            logger.info("VoskSTT: stream abierto (sr=%s, ch=%s, dtype=%s)", self._samplerate, self._cfg.channels, self._cfg.dtype)
        except Exception as e:
            self._stream = None
            logger.error("VoskSTT: no se pudo abrir el stream de audio: %r", e, exc_info=True)
            raise

    def _close_stream(self) -> None:
        """Cierra el stream si existe; idempotente."""
        s = self._stream
        self._stream = None
        if s is None:
            return
        try:
            if getattr(s, "active", False):
                s.stop()
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass
        logger.debug("VoskSTT: stream cerrado")

    def _drain_queue(self) -> None:
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    # ---------------- debug ----------------
    @property
    def last_status(self) -> Optional[str]:
        """Último status del backend de audio (debug)."""
        return self._last_status
