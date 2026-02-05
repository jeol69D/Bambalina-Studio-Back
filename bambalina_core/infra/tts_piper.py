# File: bambalina_core/infra/tts_piper.py
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import soundfile as sf


class PiperTTS:
    """
    Wrapper de Piper usando la CLI oficial.
    En Windows, Piper no acepta texto por stdin correctamente.
    Así que se usa un archivo temporal .txt y redirección '<'
    """

    def __init__(
        self,
        model_name: str = "es_MX-claude-high.onnx",
        #model_name: str = "es_MX-ald-medium.onnx",
        base_dir: str = r"C:\piper",
        output_dir: str = "./data/audio",
    ) -> None:
        """

        :type model_name: str
        """
        self.base_dir = Path(base_dir)
        self.piper_binary = self.base_dir / "piper.exe"
        self.model_path = self.base_dir / "voices" / model_name
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if not self.piper_binary.exists():
            raise FileNotFoundError(f"piper.exe no encontrado en: {self.piper_binary}")

        if not self.model_path.exists():
            raise FileNotFoundError(f"Modelo Piper no encontrado: {self.model_path}")

        print(f"🔊 [PiperTTS] Iniciado con modelo {self.model_path.name}")

    # -------------------------------------------------------------
    def speak_to_dict(self, text: str) -> dict:
        """
        Genera un WAV con Piper CLI usando redirección desde un archivo .txt
        """

        if not text.strip():
            raise ValueError("Texto vacío recibido en PiperTTS")

        # Archivo de texto temporal
        tmp_txt = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        txt_path = Path(tmp_txt.name)
        txt_path.write_text(text, encoding="utf-8")

        # Archivo WAV temporal
        tmp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=self.output_dir)
        wav_path = Path(tmp_wav.name)

        # Comando Piper (sin stdin directo)
        # Importante: redirección con "< archivo.txt"
        cmd = f'"{self.piper_binary}" --model "{self.model_path}" --output_file "{wav_path}" < "{txt_path}"'

        # Ejecutar usando shell=True para permitir la redirección "<"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        # ¿Error?
        if result.returncode != 0:
            print("❌ ERROR Piper stdout:", result.stdout)
            print("❌ ERROR Piper stderr:", result.stderr)
            raise RuntimeError("Piper falló al sintetizar.")

        # Leer WAV
        audio, sr = sf.read(str(wav_path))
        duration = len(audio) / sr

        print(f"✅ [PiperTTS] Audio generado ({duration:.2f}s): {wav_path}")

        return {
            "text": text,
            "audio_path": str(wav_path),
            "duration": duration,
            "phonemes": [],
        }
