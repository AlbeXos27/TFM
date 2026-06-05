import os
import json
from pathlib import Path
from easyDataverse import Dataverse

# =========================================================
# 1. CONFIGURACIÓN DE CONEXIÓN
# =========================================================
DATAVERSE_URL = "http://localhost:8080"  # O tu servidor objetivo
API_TOKEN = "43cd9b2f-126f-4f88-b8ab-da3e2f2b909b" 
PARENT_COLLECTION = "root"  # El alias del Dataverse contenedor
REGISTRO_PID = "pids.txt"

print("🔄 Conectando con la API de Dataverse...")
dv = Dataverse(server_url=DATAVERSE_URL, api_token=API_TOKEN)
# Directorio raíz donde están indexadas todas las carpetas
DIRECTORIO_INVESTIGACIONES = Path("investigaciones")

if not DIRECTORIO_INVESTIGACIONES.exists():
    raise FileNotFoundError(f"❌ La carpeta raíz '{DIRECTORIO_INVESTIGACIONES}' no existe.")


def cargar_registros():
    """Carga los títulos ya procesados desde el archivo .txt eliminando saltos de línea"""
    registros = set() # Usamos un set en lugar de diccionario para mayor eficiencia
    if os.path.exists(REGISTRO_PID):
        with open(REGISTRO_PID, "r", encoding="utf-8") as f:
            for linea in f:
                linea_limpia = linea.strip()
                if linea_limpia:
                    registros.add(linea_limpia)
    return registros


titulos_procesados = cargar_registros()

# =========================================================
# 2. BUCLE AUTOMÁTICO DE CARPETAS
# =========================================================
for ruta_carpeta in DIRECTORIO_INVESTIGACIONES.iterdir():
    
    if ruta_carpeta.is_dir():
        ruta_json = ruta_carpeta / "metadatos.json"
        
        if not ruta_json.exists():
            print(f"⏩ Saltando carpeta '{ruta_carpeta.name}': No contiene 'metadatos.json'")
            continue
            
        print(f"\n🚀 Procesando investigación: {ruta_carpeta.name.upper()}")
        print("-" * 60)
        
        try:
            # Leer los metadatos específicos primero para validar duplicados
            with open(ruta_json, "r", encoding="utf-8") as f:
                meta = json.load(f)
            
            titulo_dataset = meta.get("titulo", f"Dataset: {ruta_carpeta.name}").strip()

            if titulo_dataset in titulos_procesados:
                print(f"⏩ Saltando '{titulo_dataset}': Ya fue subido previamente.")
                continue

            # Inicializamos un objeto dataset limpio
            dataset = dv.create_dataset()
            
            print("📝 Mapeando metadatos estructurados...")
            dataset.citation.title = titulo_dataset
            dataset.citation.add_ds_description(value=meta.get("contexto_general", "Sin descripción."))
            dataset.citation.subject = ["Social Sciences"]

            # =========================================================
            # 3. MAPEO DINÁMICO DE AUTORES
            # =========================================================
            primer_autor_nombre = "Contacto de Investigación"
            primer_autor_email = "investigacion@uca.es"

            for i, autor_data in enumerate(meta.get("autores", [])):
                nombre = autor_data.get("nombre")
                orcid = autor_data.get("orcid", "").strip()
                inst = autor_data.get("institucion", "")
                
                institucion = ", ".join(inst) if isinstance(inst, list) else str(inst)
                    
                if nombre:
                    if i == 0:
                        primer_autor_nombre = nombre
                        
                    # Solo enviar identifier_scheme si hay un ORCID real
                    dataset.citation.add_author(
                        name=nombre,
                        affiliation=institucion if institucion else None,
                        identifier_scheme="ORCID" if orcid else None,
                        identifier=orcid if orcid else None
                    )
            
            dataset.citation.add_dataset_contact(name=primer_autor_nombre, email=primer_autor_email)
            print(f"   ✓ Autores y contactos vinculados correctamente.")

            # =========================================================
            # 4. VINCULACIÓN DE ARCHIVOS
            # =========================================================
            print("📁 Vinculando archivos físicos...")

            # 1. Adjuntar papers listados en los metadatos
            papers_metadata = meta.get("papers", [])
            if papers_metadata:
                for paper_meta in papers_metadata:
                    paper_nombre = paper_meta.get("archivo")
                    if not paper_nombre:
                        continue
                    fichero_pdf = ruta_carpeta / paper_nombre
                    if fichero_pdf.exists():
                        dataset.add_file(
                            local_path=str(fichero_pdf),
                            description="Documento de trabajo original en formato PDF."
                        )
                        print(f"   ✓ Documento PDF vinculado: {paper_nombre}")
                    else:
                        print(f"   ⚠️ Paper '{paper_nombre}' no encontrado en carpeta.")
            else:
                fichero_pdf = ruta_carpeta / "paper.pdf"
                if fichero_pdf.exists():
                    dataset.add_file(
                        local_path=str(fichero_pdf),
                        description="Documento de trabajo original (Working Paper) en formato PDF."
                    )
                    print(f"   ✓ Documento PDF vinculado: {fichero_pdf.name}")

            # 2. Adjuntar los datasets listados en el JSON
            for ds in meta.get("datasets", []):
                archivo_nombre = ds.get("archivo")
                descripcion_archivo = ds.get("descripcion", "Archivo de datos científicos.")
                
                if archivo_nombre:
                    ruta_fichero_datos = ruta_carpeta / archivo_nombre
                    
                    if ruta_fichero_datos.exists():
                        dataset.add_file(
                            local_path=str(ruta_fichero_datos),
                            description=descripcion_archivo
                        )
                        print(f"   ✓ Fichero de datos vinculado: {archivo_nombre}")
                        
                    else:
                        print(f"   ⚠️ Archivo '{archivo_nombre}' no encontrado. Buscando fragmentos .csv...")
                        raiz_nombre = archivo_nombre.replace(".xlsx", "")
                        
                        for archivo_local in ruta_carpeta.iterdir():
                            if archivo_local.name.startswith(raiz_nombre) and archivo_local.suffix == ".csv":
                                dataset.add_file(
                                    local_path=str(archivo_local),
                                    description=f"Hoja derivada de {archivo_nombre}. {descripcion_archivo}"
                                )
                                print(f"   ✓ Fragmento derivado vinculado: {archivo_local.name}")
        
            # =========================================================
            # 5. SUBIDA AL SERVIDOR Y REGISTRO (SEGURO)
            # =========================================================
            # Escribimos en el registro SÓLO si la subida fue exitosa
            with open(REGISTRO_PID, "a", encoding="utf-8") as f:
                f.write(f"{titulo_dataset}\n")

            print("📤 Transmitiendo datos hacia Dataverse...")
            
            # Subimos primero. Si falla, irá al 'except' sin escribir en el TXT
            dataset_pid = dataset.upload(dataverse_name=PARENT_COLLECTION)

            print(f"🎉 ¡Éxito! Creado en Dataverse.")
            print(f"🔗 PID asignado: {dataset_pid}")


                
        except Exception as e:
            print(f"❌ Error procesando la carpeta '{ruta_carpeta.name}': {e}")
            print("⏭️ Continuando con la siguiente investigación...")

print("\n🏁 Pipeline masivo finalizado.")