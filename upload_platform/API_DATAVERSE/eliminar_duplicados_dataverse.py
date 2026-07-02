import os
from easyDataverse import Dataverse

# 1. Configuración de conexión
dv = Dataverse(server_url="http://localhost:8080", api_token="43cd9b2f-126f-4f88-b8ab-da3e2f2b909b")

# CAMBIAR ESTA VARIABLE PARA ESPECIFICAR QUÉ SUBCOLECCIÓN BORRAR COMPLETAMENTE
SUBCOLECCION_A_BORRAR = "giiuca"  # Ej: "endometriosis-menopausia"

# 2. Ruta del archivo pids.txt
directorio_script = os.path.dirname(os.path.abspath(__file__))  # API_DATAVERSE
directorio_upload_platform = os.path.dirname(directorio_script) # upload_platform
directorio_tfm = os.path.dirname(directorio_upload_platform)    # TFM
ruta_pids_absoluta = os.path.join(directorio_tfm, "pids.txt")

print(f"🔍 Buscando contenidos en la subcolección '{SUBCOLECCION_A_BORRAR}'...")

def borrar_contenido_recursivo(coleccion_alias):
    """Borra recursivamente todos los datasets y subcolecciones dentro de una colección."""
    datasets_borrados = 0
    colecciones_borradas = 0
    
    try:
        response = dv.native_api.get_dataverse_contents(coleccion_alias)
        contenido = response.json()
    except Exception as e:
        print(f"❌ Error al acceder a la colección '{coleccion_alias}': {e}")
        return 0, 0
    
    # Separamos los elementos por tipo
    datasets_a_borrar = []
    subcolecciones_a_borrar = []
    
    for item in contenido.get("data", []):
        if item.get("type") == "dataset":
            datasets_a_borrar.append(item)
        elif item.get("type") == "dataverse":
            subcolecciones_a_borrar.append(item)
    
    print(f"📋 Se encontraron {len(datasets_a_borrar)} datasets en '{coleccion_alias}'")
    
    # 1. PRIMERO: Eliminar datasets
    for item in datasets_a_borrar:
        protocolo_pid = f"doi:{item.get('authority')}/{item.get('identifier')}"
        try:
            dv.native_api.delete_dataset(identifier=protocolo_pid)
            datasets_borrados += 1
            print(f"  ✅ Dataset borrado: {protocolo_pid}")
        except Exception as e:
            print(f"  ⚠️ No se pudo borrar {protocolo_pid}: {e}")
    
    # 2. SEGUNDO: Procesar subcolecciones recursivamente
    for subcoleccion in subcolecciones_a_borrar:
        alias_subcoleccion = subcoleccion.get("id")
        print(f"\n  🔄 Vaciando subcolección: {alias_subcoleccion}...")
        sub_datasets, sub_colecciones = borrar_contenido_recursivo(alias_subcoleccion)
        datasets_borrados += sub_datasets
        colecciones_borradas += sub_colecciones
        
        # Luego borra la subcolección vacía
        try:
            dv.native_api.delete_dataverse(alias_subcoleccion)
            colecciones_borradas += 1
            print(f"  ✅ Subcolección borrada: {alias_subcoleccion}")
        except Exception as e:
            print(f"  ⚠️ No se pudo borrar subcolección {alias_subcoleccion}: {e}")
    
    return datasets_borrados, colecciones_borradas

# 3. Ejecutar eliminación recursiva en la subcolección especificada
print("=" * 60)
datasets_totales, colecciones_totales = borrar_contenido_recursivo(SUBCOLECCION_A_BORRAR)
print("=" * 60)

# 4. Eliminación del archivo pids.txt
if os.path.exists(ruta_pids_absoluta):
    os.remove(ruta_pids_absoluta)
    print(f"🗑️ El archivo '{ruta_pids_absoluta}' ha sido eliminado.")
else:
    print(f"ℹ️ El archivo pids.txt no existe.")

print(f"\n✨ ¡Limpieza completada!")
print(f"   🔹 Datasets eliminados: {datasets_totales}")
print(f"   🔹 Subcolecciones eliminadas: {colecciones_totales}")
print(f"   🔹 La subcolección '{SUBCOLECCION_A_BORRAR}' está ahora vacía (aún existe pero sin contenido)")
