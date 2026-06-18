import os
from easyDataverse import Dataverse

# 1. Configuración de conexión
dv = Dataverse(server_url="http://localhost:8080", api_token="43cd9b2f-126f-4f88-b8ab-da3e2f2b909b")
COLECCION_PADRE = "giiuca" 

# 2. 🚀 SOLUCIÓN A LA RUTA DEL ARCHIVO:
# Obtenemos la ruta absoluta de la carpeta raíz 'TFM' subiendo dos niveles desde este script
directorio_script = os.path.dirname(os.path.abspath(__file__))  # API_DATAVERSE
directorio_upload_platform = os.path.dirname(directorio_script) # upload_platform
directorio_tfm = os.path.dirname(directorio_upload_platform)    # TFM

# Unimos la ruta para apuntar exactamente a C:\Users\alber\Desktop\Alberto\TFM\pids.txt
ruta_pids_absoluta = os.path.join(directorio_tfm, "pids.txt")

print(f"🔍 Buscando contenidos en la colección '{COLECCION_PADRE}'...")
response = dv.native_api.get_dataverse_contents(COLECCION_PADRE)
contenido = response.json()

datasets_borrados = 0

# 3. Bucle de eliminación de datasets en Dataverse
for item in contenido.get("data", []):
    if item.get("type") == "dataset":
        protocolo_pid = f"doi:{item.get('authority')}/{item.get('identifier')}"
        
        try:
            dv.native_api.delete_dataset(identifier=protocolo_pid)
            datasets_borrados += 1
            print(f"🗑️ Eliminado borrador: {protocolo_pid} -> ✅")
        except Exception as e:
            print(f"⚠️ No se pudo borrar {protocolo_pid}: {e}")

print("-" * 60)

# 4. Eliminación del archivo pids.txt en la ruta correcta
if os.path.exists(ruta_pids_absoluta):
    os.remove(ruta_pids_absoluta)
    print(f"🗑️ El archivo '{ruta_pids_absoluta}' ha sido eliminado por completo.")
else:
    print(f"⚠️ El archivo no se encontró en: '{ruta_pids_absoluta}'")

print(f"\n✨ ¡Limpieza completada! Se han eliminado {datasets_borrados} datasets de prueba.")