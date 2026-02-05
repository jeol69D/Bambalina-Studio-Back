"""
tts_coqui.py — Bambalina Studio
Motor de voz natural basado en Coqui TTS (offline, compatible con todos los modelos).
"""

from pathlib import Path
from typing import Optional, Dict, Any
from TTS.api import TTS
import soundfile as sf
import tempfile
import json
import numpy as np


class CoquiTTS:
    """
    Motor TTS neuronal (Coqui).
    Genera voz natural y devuelve metadatos con duración y (si existen) alineamientos.
    """

    def __init__(
        self,
        model_name: str = "tts_models/es/css10/vits",
        output_dir: str = "./data/audio",
        sample_rate: int = 22050,
        use_cuda: bool = False,
    ):
        self.model_name = model_name
        self.sample_rate = sample_rate
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        print(f"🔊 [CoquiTTS] Cargando modelo: {model_name} ...")
        self.tts = TTS(model_name).to("cuda" if use_cuda else "cpu")

    # ----------------------------------------------------------
    def warm_up(self) -> None:
        """Inicializa kernels/caches del modelo para reducir la 1ª latencia."""
        try:
            _ = self.tts.tts("ok")
            print("✅ Warm-up completado.")
        except Exception as e:
            print(f"⚠️ [CoquiTTS] Warm-up falló: {e}")

    # ----------------------------------------------------------
    def speak(self, text: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Genera un archivo de audio WAV desde texto y devuelve metadatos.
        Retorna:
        {
            "path": ruta del archivo WAV,
            "duration": duración (seg),
            "alignments": [...]
        }
        """
        if not text.strip():
            raise ValueError("Texto vacío en CoquiTTS.speak()")

        if filename is None:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False, dir=self.output_dir
            )
            filename = tmp.name

        print(f"🗣️ [CoquiTTS] Generando audio para: \"{text}\"")

        wav, alignments = None, []

        try:
            # algunos modelos devuelven lista, otros tupla (wav, align, ...)
            result = self.tts.tts(text, return_alignments=True)
            if isinstance(result, tuple) and len(result) > 1:
                wav = result[0]
                align_data = result[1]
                if isinstance(align_data, (list, tuple)):
                    for item in align_data:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            alignments.append({"value": str(item[0]), "t": float(item[1])})
            elif isinstance(result, (list, np.ndarray)):
                wav = result
            else:
                # fallback si devuelve algo inesperado
                wav = self.tts.tts(text)
        except Exception as e:
            print(f"⚠️ [CoquiTTS] Modo fallback por excepción: {e}")
            wav = self.tts.tts(text)

        # Verifica que se haya generado audio
        if wav is None or len(wav) == 0:
            raise RuntimeError("No se generó audio con CoquiTTS.")

        # Guardar el WAV
        sf.write(filename, wav, self.sample_rate)
        duration = len(wav) / self.sample_rate
        print(f"✅ [CoquiTTS] Audio guardado en: {filename}")

        return {
            "path": filename,
            "duration": duration,
            "alignments": alignments,
        }

    # ----------------------------------------------------------
    def speak_to_dict(self, text: str) -> Dict[str, Any]:
        """Versión de conveniencia para retorno tipo JSON."""
        result = self.speak(text)
        phonemes = [
            {"value": p.get("value", ""), "t": p.get("t", 0.0)}
            for p in result.get("alignments", [])
        ]
        return {
            "text": text,
            "audio_path": result["path"],
            "duration": result["duration"],
            "phonemes": phonemes,
        }


if __name__ == "__main__":
    tts = CoquiTTS()
    tts.warm_up()
    sample_text = "Hola, soy la voz de Bambalina Studio."
    result = tts.speak_to_dict(sample_text)
    print(json.dumps(result, indent=2, ensure_ascii=False))
