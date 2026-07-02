import os
import json
import re
from pathlib import Path
from easyDataverse import Dataverse
from client_ia.request_Groq import extraer_subjects

def cargar_configuracion(ruta_config="config.json"):
    """Lee el archivo de configuración JSON desde la misma carpeta del script."""
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    ruta_config_absoluta = os.path.join(directorio_actual, ruta_config)
    
    if not os.path.exists(ruta_config_absoluta):
        raise FileNotFoundError(f"❌ No se encontró el archivo de configuración: {ruta_config_absoluta}")
        
    with open(ruta_config_absoluta, "r", encoding="utf-8") as f:
        return json.load(f)


def ejecutar_pipeline_dataverse(config):
    """
    Escanea un directorio en busca de carpetas con 'metadatos.json',
    crea un Dataverse propio para cada proyecto si no existe, sube los 
    elementos a ese Dataverse específico y devuelve un resumen.
    """
    resumen = {
        "carpetas_totales_detectadas": 0,
        "carpetas_procesadas_con_exito": 0,
        "carpetas_saltadas": 0,
        "carpetas_con_error": 0,
        "articulos_subidos_nuevos": 0,
        "articulos_saltados_duplicados": 0
    }

    print("🔄 Conectando con la API de Dataverse...")
    try:
        dv = Dataverse(
            server_url=config.get("DATAVERSE_URL"), 
            api_token=config.get("API_TOKEN")
        )
    except Exception as e:
        print(f"❌ Error crítico al conectar con Dataverse: {e}")
        return resumen

    dir_investigaciones = Path(config.get("DIRECTORIO_INVESTIGACIONES", "investigaciones"))
    if not dir_investigaciones.exists():
        print(f"❌ Error: La carpeta raíz '{dir_investigaciones}' no existe.")
        return resumen

    archivo_registro = config.get("ARCHIVO_REGISTRO", "pids.txt")
    raiz_coleccion = config.get("PARENT_COLLECTION")  # Colección madre (ej: "root" o "giiuca")
    
    # Datos de contacto obligatorios
    contacto_nombre = config.get("CONTACT_NAME", "Gestor de Investigación")
    contacto_email = config.get("CONTACT_EMAIL", "admin@dataverse.local")

    # Cargar registros ya procesados
    titulos_procesados = set()
    if os.path.exists(archivo_registro):
        with open(archivo_registro, "r", encoding="utf-8") as f:
            for linea in f:
                linea_limpia = linea.strip()
                if linea_limpia:
                    titulos_procesados.add(linea_limpia)

    # 1. BUCLE DE CARPETAS
    for ruta_carpeta in dir_investigaciones.iterdir():
        if not ruta_carpeta.is_dir():
            continue
            
        resumen["carpetas_totales_detectadas"] += 1
        ruta_json = ruta_carpeta / "metadatos.json"
        
        if not ruta_json.exists():
            print(f"⏩ Saltando carpeta '{ruta_carpeta.name}': No contiene 'metadatos.json'")
            resumen["carpetas_saltadas"] += 1
            continue
            
        print(f"\n🚀 Procesando carpeta de investigación: {ruta_carpeta.name.upper()}")
        print("=" * 60)
        
        try:
            with open(ruta_json, "r", encoding="utf-8") as f:
                meta = json.load(f)
            
            # Obtener el nombre del proyecto (Ej: "Menopausia", "Endometriosis")
            proyecto_nombre = meta.get("proyecto_nombre", ruta_carpeta.name).strip()
            
            # Crear un alias válido para la URL de Dataverse (minúsculas, sin espacios ni caracteres especiales)
            proyecto_alias = re.sub(r'[^a-zA-Z0-9_-]', '', proyecto_nombre.lower().replace(" ", "_"))

            articulos = meta.get("articulos", [])
            datasets_globales = meta.get("datasets", [])

            if not articulos and not datasets_globales:
                print(f"⚠️ La carpeta {ruta_carpeta.name} no contiene ni artículos ni datasets.")
                resumen["carpetas_saltadas"] += 1
                continue

            # =================================================================
            # 🚀 ROBUSTO: VERIFICAR Y CREAR DATAVERSE (CORREGIDO PARA NATIVE_API)
            # =================================================================
            print(f"📁 Verificando existencia de la colección dedicada: '{proyecto_alias}'...")
            
            coleccion_existe = False
            try:
                res = dv.native_api.get_dataverse(proyecto_alias)
                
                if isinstance(res, dict) and res.get("status") == "ERROR":
                    coleccion_existe = False
                elif hasattr(res, "status_code") and res.status_code == 404:
                    coleccion_existe = False
                else:
                    coleccion_existe = True
                    print(f"ℹ️ La colección '{proyecto_alias}' ya existe. Se usará este contenedor.")
            except Exception:
                coleccion_existe = False

            if not coleccion_existe:
                print(f"✨ Creando nueva colección dedicada en '{raiz_coleccion}' con alias '{proyecto_alias}'...")
                try:
                    # Definimos el payload JSON requerido por la API nativa de Dataverse
                    dataverse_data = {
                        "name": proyecto_nombre,
                        "alias": proyecto_alias,
                        "dataverseContacts": [
                            {
                                "contactEmail": contacto_email
                            }
                        ],
                        "dataverseType": "RESEARCH_PROJECT"
                    }
                    
                    # Convertimos a string JSON el diccionario estructurado
                    dataverse_json = json.dumps(dataverse_data)
                    
                    # Llamamos directamente a la API nativa adjunta en easyDataverse
                    dv.native_api.create_dataverse(raiz_coleccion, dataverse_json)
                    print(f"✅ ¡Colección Dataverse '{proyecto_nombre}' creada con éxito!")
                    
                except Exception as e_creacion:
                    if "already exists" in str(e_creacion).lower():
                        print(f"ℹ️ El servidor indica que '{proyecto_alias}' ya existe de forma interna. Continuamos.")
                    else:
                        print(f"❌ Error real al intentar crear la colección '{proyecto_alias}': {e_creacion}")
                        print(f"⚠️ Se aborta el proceso de esta carpeta para prevenir fallos en cadena.")
                        resumen["carpetas_con_error"] += 1
                        continue

            coleccion_destino = proyecto_alias

            # =================================================================
            # CASO A: EL JSON TIENE ARTÍCULOS
            # =================================================================
            if articulos:
                for idx, articulo in enumerate(articulos, start=1):
                    titulo_dataset = articulo.get("titulo_documento", "").strip()
                    if not titulo_dataset:
                        titulo_dataset = f"Dataset {proyecto_nombre} - Elemento {idx}"

                    print(f"\n📄 [Articulo {idx}/{len(articulos)}] Evaluando: '{titulo_dataset}'")

                    if titulo_dataset in titulos_procesados:
                        print(f"⏩ Saltando: Ya fue subido previamente.")
                        resumen["articulos_saltados_duplicados"] += 1
                        continue

                    dataset = dv.create_dataset()
                    dataset.citation.title = titulo_dataset
                    dataset.citation.add_dataset_contact(name=contacto_nombre, email=contacto_email)
                    
                    dataset.citation.add_ds_description(
                        value=articulo.get("contexto_general", "Sin descripción.")
                    )
                    # Extraer subjects del contexto usando Groq
                    contexto_para_subjects = articulo.get("contexto_general", articulo.get("contexto_unico", "Sin descripción"))
                    subjects_extraidos = extraer_subjects(contexto_para_subjects, titulo_dataset)
                    dataset.citation.subject = subjects_extraidos

                    # --- CONTROL DE AUTORES REFORZADO ---
                    autores_agregados = 0
                    autores = articulo.get("autores", [])
                    if isinstance(autores, list):
                        for i, autor_data in enumerate(autores):
                            nombre = autor_data.get("nombre")
                            orcid = autor_data.get("orcid", "").strip()
                            if nombre:
                                dataset.citation.add_author(
                                    name=nombre, 
                                    identifier_scheme="ORCID" if orcid else None, 
                                    identifier=orcid if orcid else None
                                )
                                autores_agregados += 1
                    
                    if autores_agregados == 0:
                        print(f"⚠️ Campo 'authorName' ausente o vacío en el JSON. Asignando autor por defecto.")
                        dataset.citation.add_author(name=contacto_nombre)
                    # ------------------------------------
                    
                    # Vincular Archivo PDF del artículo
                    pdf_nombre = articulo.get("nombre_articulo")
                    if pdf_nombre:
                        fichero_pdf = ruta_carpeta / pdf_nombre
                        if fichero_pdf.exists():
                            dataset.add_file(local_path=str(fichero_pdf), description=f"Documento académico original: {pdf_nombre}")
                            print(f"   ✓ PDF vinculado: {pdf_nombre}")

                    # Vincular Datasets adjuntos
                    relaciones = articulo.get("relaciones_datasets", [])
                    nombres_relacionados = [r.get("nombre_dataset") for r in relaciones if r.get("nombre_dataset")]

                    if isinstance(datasets_globales, list):
                        for ds in datasets_globales:
                            archivo_nombre = ds.get("nombre_dataset")
                            if archivo_nombre in nombres_relacionados:
                                ruta_fichero_datos = ruta_carpeta / archivo_nombre
                                if ruta_fichero_datos.exists():
                                    dataset.add_file(local_path=str(ruta_fichero_datos), description=ds.get("explicacion_estructura", "Archivo de datos."))
                                    print(f"   ✓ Dataset vinculado: {archivo_nombre}")

                    print(f"📤 Transmitiendo datos hacia la colección '{coleccion_destino}'...")
                    dataset_pid = dataset.upload(dataverse_name=coleccion_destino)
                    
                    with open(archivo_registro, "a", encoding="utf-8") as f:
                        f.write(f"{titulo_dataset}\n")
                    print(f"🎉 ¡Éxito! Creado en Dataverse. PID: {dataset_pid}")
                    resumen["articulos_subidos_nuevos"] += 1

            # =================================================================
            # CASO B: EL JSON TIENE DATASETS INDEPENDIENTES
            # =================================================================
            elif datasets_globales:
                for idx, ds in enumerate(datasets_globales, start=1):
                    archivo_nombre = ds.get("nombre_dataset", "")
                    titulo_dataset = f"Dataset: {archivo_nombre}" if archivo_nombre else f"Dataset Independiente {proyecto_nombre} - {idx}"

                    print(f"\n📊 [Dataset Independiente {idx}/{len(datasets_globales)}] Evaluando: '{titulo_dataset}'")

                    if titulo_dataset in titulos_procesados:
                        print(f"⏩ Saltando: Ya fue subido previamente.")
                        resumen["articulos_saltados_duplicados"] += 1
                        continue

                    dataset = dv.create_dataset()
                    dataset.citation.title = titulo_dataset
                    dataset.citation.add_dataset_contact(name=contacto_nombre, email=contacto_email)
                    
                    descripcion_ds = ds.get("analisis_contextual", "")
                    if not descripcion_ds:
                        descripcion_ds = ds.get("explicacion_estructura", "Conjunto de datos de investigación.")
                    
                    dataset.citation.add_ds_description(value=descripcion_ds)
                    # Extraer subjects del contexto usando Groq
                    subjects_extraidos = extraer_subjects(descripcion_ds, titulo_dataset)
                    dataset.citation.subject = subjects_extraidos
                    
                    dataset.citation.add_author(name=contacto_nombre)
                    
                    if archivo_nombre:
                        ruta_fichero_datos = ruta_carpeta / archivo_nombre
                        if ruta_fichero_datos.exists():
                            dataset.add_file(
                                local_path=str(ruta_fichero_datos),
                                description=ds.get("explicacion_estructura", "Archivo de datos de investigación.")
                            )
                            print(f"   ✓ Archivo de datos vinculado: {archivo_nombre}")
                        else:
                            print(f"   ⚠️ Archivo físico '{archivo_nombre}' no encontrado en la carpeta.")

                    print(f"📤 Transmitiendo datos hacia la colección '{coleccion_destino}'...")
                    dataset_pid = dataset.upload(dataverse_name=coleccion_destino)
                    
                    with open(archivo_registro, "a", encoding="utf-8") as f:
                        f.write(f"{titulo_dataset}\n")
                    print(f"🎉 ¡Éxito! Creado en Dataverse. PID: {dataset_pid}")
                    resumen["articulos_subidos_nuevos"] += 1

            resumen["carpetas_procesadas_con_exito"] += 1
                
        except Exception as e:
            print(f"❌ Error procesando la carpeta '{ruta_carpeta.name}': {e}")
            resumen["carpetas_con_error"] += 1

    print("\n🏁 Pipeline masivo finalizado.")
    return resumen


if __name__ == "__main__":
    try:
        configuracion = cargar_configuracion()
        resultado = ejecutar_pipeline_dataverse(configuracion)
        print("\n📊 RESUMEN DE LA OPERACIÓN:")
        print(json.dumps(resultado, indent=4, ensure_ascii=False))
    except Exception as e:
        print(f"💥 Error al ejecutar el script: {e}")