# bambalina_api/main.py
from fastapi import FastAPI, WebSocket, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from pathlib import Path
from bambalina_api.runtime import SceneRuntime
from datetime import datetime

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
        
        # Notificar a todos los clientes conectados sobre el cambio
        await broadcast({
            "type": "avatar_updated",
            "avatar": {
                "name": name,
                "model": model
            }
        })
        
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

@app.get("/avatar-config")
async def get_avatar_config():
    """Endpoint para obtener la configuración actual del avatar"""
    try:
        if not SCENE_FILE.exists():
            return {
                "success": False,
                "message": "No se encontró archivo de escena"
            }
        
        with open(SCENE_FILE, 'r', encoding='utf-8') as f:
            scene_data = json.load(f)
        
        if 'meta' in scene_data and 'avatars' in scene_data['meta'] and scene_data['meta']['avatars']:
            avatar = scene_data['meta']['avatars'][0]  
            return {
                "success": True,
                "avatar": {
                    "name": avatar.get("name", ""),
                    "model": avatar.get("model", "avatar.glb"),
                    "voice": avatar.get("voice", "Helena"),
                    "gender": avatar.get("gender", "f")
                }
            }
        else:
            return {
                "success": False,
                "message": "No se encontró configuración de avatar"
            }
            
    except Exception as e:
        print(f"Error obteniendo configuración de avatar: {e}")
        raise HTTPException(status_code=500, detail=f"Error obteniendo configuración: {str(e)}")

@app.post("/save-audio")
async def save_audio(
    audio: UploadFile = File(...),
    name: str = Form(...),
    animation: str = Form(...),
    expression: str = Form(...),
    duration: str = Form(...),
    scriptLineIndex: str = Form("") 
):
    """Endpoint para recibir audios grabados con metadata en formato WAV"""
    try:
        print(f"📝 Audio WAV recibido:")
        print(f"   - Nombre: {name}")
        print(f"   - Animación: {animation}")
        print(f"   - Expresión: {expression}")
        print(f"   - Duración: {duration}")
        print(f"   - Línea del guión: {scriptLineIndex or 'No asignada'}")
        print(f"   - Archivo: {audio.filename} ({audio.content_type})")
        
        # Validar que sea un archivo WAV
        if not (audio.content_type in ["audio/wav", "audio/wave"] or 
                audio.filename.lower().endswith('.wav')):
            print(f"⚠️ Tipo de contenido recibido: {audio.content_type}")
            print(f"⚠️ Nombre de archivo: {audio.filename}")
            # No rechazar, solo advertir
            print("⚠️ Advertencia: El archivo podría no ser WAV, pero se procesará")
        
        # 1️⃣ Guardar archivo de audio
        audio_content = await audio.read()
        
        # Crear directorio de audios si no existe
        audio_dir = Path("./data/recorded_audios")
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        # Generar nombre único para el archivo - FORMATO WAV
        import uuid
        audio_id = uuid.uuid4().hex
        audio_filename = f"linea{scriptLineIndex}_{audio_id}_{name}.wav"
        audio_path = audio_dir / audio_filename
        
        # Guardar archivo WAV directamente
        with open(audio_path, "wb") as f:
            f.write(audio_content)
        
        print(f"✅ Audio WAV guardado en: {audio_path}")
        
        # 2️⃣ Actualizar JSON si se especificó una línea
        json_updated = False
        if scriptLineIndex and scriptLineIndex.strip():
            try:
                line_index = int(scriptLineIndex)
                
                # Leer el archivo JSON actual
                if SCENE_FILE.exists():
                    with open(SCENE_FILE, 'r', encoding='utf-8') as f:
                        scene_data = json.load(f)
                    
                    # Verificar que existe el script y el índice es válido
                    if "script" in scene_data and 0 <= line_index < len(scene_data["script"]):
                        # Actualizar la línea específica
                        old_animation = scene_data["script"][line_index].get("animation", "N/A")
                        old_expression = scene_data["script"][line_index].get("expression", "N/A")
                        
                        scene_data["script"][line_index]["animation"] = animation
                        scene_data["script"][line_index]["expression"] = expression
                        
                        # Guardar el archivo JSON actualizado
                        with open(SCENE_FILE, 'w', encoding='utf-8') as f:
                            json.dump(scene_data, f, ensure_ascii=False, indent=2)
                        
                        print(f"✅ JSON actualizado:")
                        print(f"   - Línea {line_index}: '{scene_data['script'][line_index]['text'][:50]}...'")
                        print(f"   - Animación: {old_animation} → {animation}")
                        print(f"   - Expresión: {old_expression} → {expression}")
                        
                        json_updated = True
                        
                        # Notificar a clientes sobre actualización del guión
                        await broadcast({
                            "type": "script_updated",
                            "data": {
                                "lineIndex": line_index,
                                "animation": animation,
                                "expression": expression,
                                "text": scene_data["script"][line_index]["text"]
                            }
                        })
                        
                    else:
                        print(f"⚠️ Índice de línea inválido: {line_index} (script tiene {len(scene_data.get('script', []))} líneas)")
                        
                else:
                    print(f"⚠️ Archivo JSON no encontrado: {SCENE_FILE}")
                    
            except ValueError:
                print(f"⚠️ scriptLineIndex no es un número válido: {scriptLineIndex}")
        
        # 3️⃣ Crear entrada de metadata
        new_entry = {
            "id": audio_id,
            "filename": audio_filename,
            "original_name": name,
            "animation": animation,
            "expression": expression,
            "duration": duration,
            "script_line_index": scriptLineIndex if scriptLineIndex.strip() else None,
            "timestamp": datetime.now().isoformat(),
            "content_type": "audio/wav",
            "file_path": str(audio_path)
        }
        
        # 4️⃣ Guardar metadata
        metadata_file = Path("./data/recorded_audios/metadata.json")
        existing_metadata = []
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    existing_metadata = json.load(f)
            except:
                pass
        
        existing_metadata.append(new_entry)
        
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(existing_metadata, f, ensure_ascii=False, indent=2)
        
        # 5️⃣ Notificar a clientes conectados
        await broadcast({
            "type": "audio_saved",
            "data": new_entry
        })
        
        # 6️⃣ Respuesta final
        return {
            "success": True,
            "message": f"Audio WAV guardado exitosamente{' y JSON actualizado' if json_updated else ''}",
            "data": new_entry
        }
        
    except Exception as e:
        print(f"❌ Error guardando audio WAV: {e}")
        raise HTTPException(status_code=500, detail=f"Error guardando audio WAV: {str(e)}")

@app.get("/script-lines")
async def get_script_lines():
    """Endpoint para obtener las líneas del script con índices"""
    try:
        if not SCENE_FILE.exists():
            raise HTTPException(status_code=404, detail="Archivo de escena no encontrado")
        
        # Leer el archivo JSON de la escena
        with open(SCENE_FILE, 'r', encoding='utf-8') as f:
            scene_data = json.load(f)
        
        # Obtener el script y agregar índices
        script_lines = []
        for index, line in enumerate(scene_data.get("script", [])):
            script_lines.append({
                "index": index,
                "speaker": line.get("speaker", ""),
                "text": line.get("text", ""),
                "animation": line.get("animation", "Idle"),
                "expression": line.get("expression", "neutral")
            })
        
        return {
            "success": True,
            "message": f"Se encontraron {len(script_lines)} líneas",
            "lines": script_lines
        }
        
    except Exception as e:
        print(f"❌ Error obteniendo líneas del script: {e}")
        raise HTTPException(status_code=500, detail=f"Error obteniendo líneas: {str(e)}")
