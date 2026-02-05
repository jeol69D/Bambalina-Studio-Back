# bambalina_api/main.py
from fastapi import FastAPI, WebSocket
import asyncio
from bambalina_api.runtime import SceneRuntime

app = FastAPI()
runtime = SceneRuntime()

clients = set()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    print(f"✅ Cliente WS conectado: {ws.client}")
    clients.add(ws)
    try:
        while True:
            msg = await ws.receive_text()
            print(f"💬 Mensaje recibido del cliente: {msg}")
    except Exception as e:
        print(f"⚠️ Cliente WS desconectado: {ws.client} ({e})")
        clients.remove(ws)

async def broadcast(payload: dict):
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(payload)
        except Exception as e:
            print(f"❌ Error enviando a cliente {ws.client}: {e}")
            dead.append(ws)
    for ws in dead:
        clients.remove(ws)

@app.on_event("startup")
async def on_startup():
    loop = asyncio.get_running_loop()
    runtime.bind_loop(loop)
    runtime.start()
    print("🎬 Servidor Bambalina iniciado (modo interactivo)")

def safe_emit(payload: dict):
    try:
        loop = asyncio.get_running_loop()
        asyncio.create_task(broadcast(payload))
    except RuntimeError:
        if runtime._loop and runtime._loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast(payload), runtime._loop)
        else:
            print("⚠️ No hay loop activo para broadcast:", payload)

runtime.on_event = safe_emit
