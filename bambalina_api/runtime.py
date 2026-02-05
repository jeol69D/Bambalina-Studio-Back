# ===========================================================
# File: bambalina_api/runtime.py
# Integración PiperTTS (CLI puro) — Bambalina Studio (estable)
# ===========================================================
from __future__ import annotations
import asyncio, threading, time
from pathlib import Path
from typing import Optional, Callable, List, Tuple, Dict
import sounddevice as sd
import soundfile as sf
import numpy as np
import librosa

from bambalina_core.models.parser_scene import load_scene, SceneLine
from bambalina_core.director import EnsayoDirector
from bambalina_core.infra.stt_vosk import VoskSTT, STTConfig
from bambalina_core.infra.tts_piper import PiperTTS


SCENE_PATH = Path("./data/escena_demo.json")


# ===========================================================
# 🔠 Fonemas aproximados (fallback)
# ===========================================================
def approx_phonemes(text: str, dur: float, cps: float = 15.0) -> Tuple[List[dict], float]:
    phonemes = []
    if not text.strip():
        return phonemes, 0.0

    total_chars = len([ch for ch in text if ch.strip()])
    if total_chars == 0:
        return phonemes, dur

    time_per_char = dur / total_chars
    t = 0.0

    for ch in text:
        if ch.strip():
            phonemes.append({"t": round(t, 3), "p": "O"})
            t += time_per_char * 0.5
            phonemes.append({"t": round(t, 3), "p": "C"})
            t += time_per_char * 0.5

    return phonemes, dur


# ===========================================================
# 🎧 Cálculo de energía (lipsync)
# ===========================================================
def energy_phonemes(path: str, threshold: float = 0.15) -> Dict[str, any]:
    result = {"phonemes": [], "mean_energy": 0.0, "peak_energy": 0.0, "var_energy": 0.0}

    try:
        y, sr = librosa.load(path, sr=None, mono=True)

        frame_length = int(sr * 0.05)   # 50ms
        hop_length = frame_length // 2  # 25ms

        energy = np.array([
            np.sqrt(np.mean(y[i:i + frame_length] ** 2))
            for i in range(0, len(y), hop_length)
        ])

        energy /= np.max(energy) + 1e-9
        times = np.linspace(0, len(y) / sr, len(energy))

        result["mean_energy"] = float(np.mean(energy))
        result["peak_energy"] = float(np.max(energy))
        result["var_energy"] = float(np.var(energy))

        phonemes = []
        for t, e in zip(times, energy):
            p = "O" if e > threshold else "C"
            phonemes.append({"t": round(float(t), 3), "p": p})

        result["phonemes"] = phonemes

    except Exception as e:
        print(f"[WARN] energy_phonemes(): {e}")

    return result


# ===========================================================
# 🎬 Runtime principal
# ===========================================================
class SceneRuntime:
    def __init__(self) -> None:
        self.scene = None
        self.director: Optional[EnsayoDirector] = None
        self.stt: Optional[VoskSTT] = None
        self.tts: Optional[PiperTTS] = None

        self._stt_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self.on_event: Callable[[dict], None] = lambda _: None
        self.on_status: Callable[[str], None] = lambda _: None

    # -------------------------------------------------------
    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    # -------------------------------------------------------
    def start(self):
        """Carga la escena y prepara STT + TTS."""
        self.scene = load_scene(SCENE_PATH)
        humans = set(self.scene.meta.humans or [])

        # Director de escena
        self.director = EnsayoDirector(
            script=self.scene.script,
            human_characters=humans,
            threshold=self.scene.meta.similarity_threshold,
        )

        # 🔊 TTS
        self.tts = PiperTTS()
        print("🔊 PiperTTS operativo (CLI puro)")

        # 🎤 STT
        self.stt = VoskSTT(model_path="./bambalina_core/models/vosk/es", config=STTConfig())
        self._stop.clear()
        self._pause.clear()
        self.stt.start()

        self._stt_thread = threading.Thread(target=self._stt_loop, daemon=True)
        self._stt_thread.start()

        self._emit_status(f"🎬 Escena lista: {self.scene.meta.title}")
        self._schedule(self._drive_virtuals_then_listen())

    # -------------------------------------------------------
    def stop(self):
        self._stop.set()
        try:
            self.stt.stop()
        except Exception:
            pass

        if self._stt_thread and self._stt_thread.is_alive():
            self._stt_thread.join(timeout=1.0)

        self._emit_status("⏹ Escena detenida")

    # -------------------------------------------------------
    def _stt_loop(self):
        assert self.stt and self.director

        while not self._stop.is_set():
            if self._pause.is_set():
                time.sleep(0.05)
                continue

            try:
                text = self.stt.read(timeout=0.2)
            except Exception as e:
                self._emit_status(f"STT: {e}")
                continue

            if not text:
                continue

            self._emit({"event": "heard", "text": text})

            try:
                advanced = self.director.feed_transcript(text)
            except Exception as e:
                self._emit_status(f"director: {e}")
                continue

            if advanced:
                self._schedule(self._drive_virtuals_then_listen())

    # -------------------------------------------------------
    async def _drive_virtuals_then_listen(self):
        if not self.director:
            return

        d = self.director

        # Esperando turno humano
        if d.is_human_turn():
            line = d.script[d.idx]
            self._emit({
                "event": "human_turn",
                "index": d.idx,
                "speaker": line.speaker,
                "expected": line.text
            })
            return

        # 🔇 Pausar micrófono
        try:
            self._pause.set()
            self.stt.pause()
            self._emit_status("🎧 STT pausado")
        except:
            pass

        # Ejecutar todas las líneas virtuales seguidas
        while d.idx < len(d.script) and not d.is_human_turn():

            line: SceneLine = d.script[d.idx]

            # ---- SINTETIZAR VOZ ----
            async def synth(text: str):
                def _task():
                    return self.tts.speak_to_dict(text)
                return await asyncio.to_thread(_task)

            try:
                print(f"🎙️ Sintetizando: {line.text[:80]}...")
                info = await synth(line.text)
                wav_path = info["audio_path"]
                dur_real = info["duration"]
            except Exception as e:
                self._emit_status(f"TTS error: {e}")
                d.idx += 1
                continue

            # ---- LIPSYNC ----
            energy_data = energy_phonemes(wav_path)
            phon = energy_data.get("phonemes", []) or approx_phonemes(line.text, dur_real)[0]

            # ---- EMOCIÓN ----
            mean_e = energy_data.get("mean_energy", 0.0)
            expression = line.expression or (
                "excited" if mean_e > 0.5 else
                "happy" if mean_e > 0.3 else
                "neutral"
            )

            # ---- EVENTO START ----
            self._emit({
                "event": "line_start",
                "index": d.idx,
                "speaker": line.speaker,
                "text": line.text,
                "animation": line.animation or "Talking_1",
                "expression": expression,
                "duration_est": dur_real,
                "phonemes": phon,
            })

            # ---- REPRODUCCIÓN ----
            async def play(path: str):
                def _play():
                    data, sr = sf.read(path)
                    sd.play(data, sr)
                    sd.wait()
                return await asyncio.to_thread(_play)

            await play(wav_path)

            self._emit({"event": "line_end", "index": d.idx})
            d.idx += 1

        # ---- REANUDAR MICRÓFONO ----
        try:
            self.stt.resume()
            self._pause.clear()
            self._emit_status("🎤 STT reanudado")
        except:
            pass

        # Si se acabó el guion
        if d.idx >= len(d.script):
            self._emit({"event": "finished"})
            return

        # Si sigue humano
        if d.is_human_turn():
            line = d.script[d.idx]
            self._emit({
                "event": "human_turn",
                "index": d.idx,
                "speaker": line.speaker,
                "expected": line.text
            })

    # -------------------------------------------------------
    def _schedule(self, coro):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        else:
            threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()

    # -------------------------------------------------------
    def _emit(self, payload: dict):
        try:
            print(f"📤 EVENTO: {payload.get('event')} | {payload.get('speaker')}")
            self.on_event(payload)
        except:
            pass

    def _emit_status(self, msg: str):
        print(msg)
        try:
            self.on_status(msg)
        except:
            pass
