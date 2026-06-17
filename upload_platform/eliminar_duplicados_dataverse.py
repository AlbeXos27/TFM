from easyDataverse import Dataverse
import os
dv = Dataverse(server_url="http://localhost:8080", api_token="43cd9b2f-126f-4f88-b8ab-da3e2f2b909b")
COLECCION_PADRE = "root" 

print(f"🔍 Buscando contenidos en la colección '{COLECCION_PADRE}'...")
archivo = "pids.txt"
response = dv.native_api.get_dataverse_contents(COLECCION_PADRE)
contenido = response.json()

datasets_borrados = 0

for item in contenido.get("data", []):
    if item.get("type") == "dataset":
        protocolo_pid = f"doi:{item.get('authority')}/{item.get('identifier')}"
        
        try:
            # Ahora sí, usando 'identifier'
            dv.native_api.delete_dataset(identifier=protocolo_pid)
            datasets_borrados += 1
            print(f"🗑️ Eliminado borrador: {protocolo_pid} -> ✅")
        except Exception as e:
            print(f"⚠️ No se pudo borrar {protocolo_pid}: {e}")

if os.path.exists(archivo):
    os.remove(archivo)
    print(f"🗑️ El archivo '{archivo}' ha sido eliminado por completo.")
else:
    print(f"⚠️ El archivo '{archivo}' no existía.")


print(f"\n✨ ¡Limpieza completada! Se han eliminado {datasets_borrados} datasets de prueba.")