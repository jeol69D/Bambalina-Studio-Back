"""
ws_sync.py — Bambalina-Studio
Servidor WebSocket que envía fonemas y animaciones sincronizadas
al frontend React (AvatarController.jsx) mientras reproduce el audio.

Usa CoquiTTS
"""

import asyncio
import websockets
import json
import threading
import soundfile as sf
import sounddevice as sd
from pathlib import Path
from bambalina_core.infra.tts_coqui import CoquiTTS



# -------------------------------------------------------------------
# CONFIGURACIÓN
# -------------------------------------------------------------------
WS_HOST = "localhost"
WS_PORT = 8765
AUDIO_DIR = Path("./data/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------------------------
# MOTOR DE VOZ
# -------------------------------------------------------------------

ENGINE_MODE = "coqui"

if ENGINE_MODE == "coqui":
    tts_engine = CoquiTTS(model_name="tts_models/es/css10/vits")
else:
    pass


# -------------------------------------------------------------------
# FUNCIONES AUXILIARES
# -------------------------------------------------------------------
def play_audio(path: str):
    """Reproduce el audio generado (no bloqueante)."""
    data, sr = sf.read(path)
    sd.play(data, sr)
    sd.wait()


def build_ws_payload(phonemes, duration: float):
    """Convierte fonemas de Coqui a mensajes para el frontend."""
    events = []
    for ph in phonemes:
        events.append({
            "type": "phoneme",
            "t": round(float(ph["t"]), 3),
            "value": ph["value"],
        })
    # Cada 2 s agregamos un parpadeo como animación de ejemplo
    blink_events = []
    t = 0.0
    while t < duration:
        blink_events.append({
            "type": "animation",
            "t": round(t, 2),
            "value": "blink"
        })
        t += 2.0
    return {
        "type": "batch",
        "phonemes": events,
        "actions": blink_events,
    }


# -------------------------------------------------------------------
# WEBSOCKET SERVER
# -------------------------------------------------------------------
async def handle_client(websocket):
    print("🎧 Cliente conectado al WS Sync")

    async for message in websocket:
        try:
            req = json.loads(message)
        except Exception:
            continue

        if req.get("type") == "tts":
            text = req.get("text", "").strip()
            if not text:
                continue

            print(f"🗣️ Generando voz para: {text}")

            # 1️⃣ Generar audio + fonemas
            if ENGINE_MODE == "coqui":
                out = tts_engine.speak_to_dict(text)
                path = out["audio_path"]
                duration = out["duration"]
                phonemes = out.get("phonemes", [])
            else:
                pass

            # 2️⃣ Enviar lote inicial de eventos al frontend
            payload = build_ws_payload(phonemes, duration)
            await websocket.send(json.dumps(payload))

            # 3️⃣ Reproducir audio localmente
            threading.Thread(target=play_audio,
                             args=(str(path),), daemon=True).start()

            print(f"✅ Audio y eventos enviados ({len(phonemes)} fonemas)")

        else:
            print("❓ Mensaje desconocido:", req)


async def main():
    print(f"🚀 Servidor WS-Sync ejecutándose en ws://{WS_HOST}:{WS_PORT}")
    async with websockets.serve(handle_client, WS_HOST, WS_PORT):
        await asyncio.Future()  # correr para siempre


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 WS Sync detenido por usuario.")
