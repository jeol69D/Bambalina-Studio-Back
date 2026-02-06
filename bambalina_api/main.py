# bambalina_api/main.py
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from pathlib import Path
from bambalina_api.runtime import SceneRuntime

app = FastAPI()

# Configurar CORS para permitir requests desde el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

runtime = SceneRuntime()
clients = set()

SCENE_FILE = Path("./data/escena_demo.json")

@app.post("/upload-scene")
async def upload_scene(scene_data: dict):
    """Endpoint para recibir y guardar archivos JSON de escena"""
    try:
        # Validar estructura básica del JSON
        if 'meta' not in scene_data and 'script' not in scene_data:
            raise HTTPException(
                status_code=400, 
                detail="JSON debe contener al menos 'meta' o 'script'"
            )

        # Leer archivo actual si existe
        current_data = {}
        if SCENE_FILE.exists():
            with open(SCENE_FILE, 'r', encoding='utf-8') as f:
                current_data = json.load(f)
        
        # Merge con nuevos datos
        if 'meta' in scene_data:
            current_data.setdefault('meta', {}).update(scene_data['meta'])
        if 'script' in scene_data:
            current_data['script'] = scene_data['script']
        
        # Guardar archivo
        with open(SCENE_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, ensure_ascii=False, indent=2)
        
        print(f"Escena actualizada desde upload: {SCENE_FILE}")
        
        # Opcional: reiniciar runtime con nueva escena
        try:
            runtime.stop()
            runtime.start()
            print("🔄 Runtime reiniciado con nueva escena")
        except Exception as e:
            print(f"⚠️ Error reiniciando runtime: {e}")
        
        return {
            "success": True, 
            "message": "Guión actualizado exitosamente",
            "file_path": str(SCENE_FILE)
        }
        
    except Exception as e:
        print(f"Error procesando upload: {e}")
        raise HTTPException(status_code=500, detail=f"Error guardando archivo: {str(e)}")

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

@app.post("/update-avatar")
async def update_avatar(avatar_data: dict):
    """Endpoint para actualizar la configuración del avatar"""
    try:
        # Validar que se envíen name y model
        if 'name' not in avatar_data or 'model' not in avatar_data:
            raise HTTPException(
                status_code=400, 
                detail="Se requieren los campos 'name' y 'model'"
            )

        name = avatar_data['name'].strip()
        model = avatar_data['model'].strip()

        if not name or not model:
            raise HTTPException(
                status_code=400, 
                detail="Los campos 'name' y 'model' no pueden estar vacíos"
            )

        # Leer archivo actual
        current_data = {}
        if SCENE_FILE.exists():
            with open(SCENE_FILE, 'r', encoding='utf-8') as f:
                current_data = json.load(f)
        
        # Asegurar que existe la estructura meta.avatars
        if 'meta' not in current_data:
            current_data['meta'] = {}
        if 'avatars' not in current_data['meta']:
            current_data['meta']['avatars'] = []
        
        # Buscar el avatar existente o crear nuevo
        if current_data['meta']['avatars']:
            # Actualizar el primer avatar (o podrías buscar por algún criterio)
            current_data['meta']['avatars'][0]['name'] = name
            current_data['meta']['avatars'][0]['model'] = model
        else:
            # Crear nuevo avatar si no existe ninguno
            current_data['meta']['avatars'].append({
                "name": name,
                "voice": "Helena",  # valor por defecto
                "gender": "f",      # valor por defecto
                "model": model
            })

        # Guardar archivo
        with open(SCENE_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, ensure_ascii=False, indent=2)
        
        print(f"Avatar actualizado: {name} -> {model}")
        
        return {
            "success": True, 
            "message": "Configuración del avatar actualizada exitosamente",
            "avatar": {
                "name": name,
                "model": model
            }
        }
        
    except Exception as e:
        print(f"Error actualizando avatar: {e}")
        raise HTTPException(status_code=500, detail=f"Error actualizando avatar: {str(e)}")
