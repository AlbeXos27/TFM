import os
import gc
import json
import chromadb
import torch
from pathlib import Path
from chromadb.utils import embedding_functions

# =====================================================================
# --- 1. CONFIGURACIÓN DE RUTAS Y MODELOS ---
# =====================================================================
RUTA_INVESTIGACIONES = Path("investigaciones")
CHROMA_PATH = "chroma_db"
RUTA_REGISTRO_URLS = Path("dataverse_urls.json")


def _cargar_urls_dataverse():
    """Carga el mapeo 'carpeta::nombre_dataset' -> URL pública de Dataverse
    generado por upload_platform/API_DATAVERSE/dataverse.py al subir."""
    if not RUTA_REGISTRO_URLS.exists():
        return {}
    try:
        with open(RUTA_REGISTRO_URLS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ No se pudo leer el registro de URLs de Dataverse: {e}")
        return {}

_collection = None


def _obtener_collection():
    """Carga el cliente de Chroma y el modelo de embeddings solo la primera vez que se necesitan.

    Se hace perezoso a propósito: bge-m3 se carga en GPU y compite por VRAM con
    el modelo local de Ollama (qwen), así que no debe residir en memoria salvo
    mientras dura la indexación.
    """
    global _collection
    if _collection is None:
        print("🔄 Inicializando cliente de ChromaDB...")
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

        print("🧠 Cargando modelo de embeddings BAAI/bge-m3...")
        embedding_bge_m3 = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="BAAI/bge-m3",
            device="cpu"
        )

        _collection = chroma_client.get_or_create_collection(
            name="datasets_metadata_v3_bge",
            embedding_function=embedding_bge_m3,
            metadata={"hnsw:space": "cosine"}
        )
    return _collection


def _liberar_collection():
    """Descarga el modelo de embeddings de la GPU al terminar de indexar."""
    global _collection
    _collection = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("🧹 Modelo de embeddings liberado de la GPU.")


# =====================================================================
# --- 2. FUNCIONES DE PROCESAMIENTO Y AUXILIARES ---
# =====================================================================

def cargar_ids_desde_chroma():
    """Recupera los IDs que ya existen en la base de datos."""
    try:
        resultado = _obtener_collection().get(include=[])
        return set(resultado['ids'])
    except Exception as e:
        print(f"⚠️ No se pudo leer ChromaDB: {e}")
        return set()


def formatear_autores(lista_autores):
    """Convierte la lista de diccionarios de autores en una cadena de texto limpia."""
    if not lista_autores or not isinstance(lista_autores, list):
        return ""
    autores_formateados = []
    for a in lista_autores:
        nombre = a.get("nombre", "").strip()
        orcid = a.get("orcid", "").strip()
        if orcid:
            autores_formateados.append(f"{nombre} (ORCID: {orcid})")
        elif nombre:
            autores_formateados.append(nombre)
    return ", ".join(autores_formateados)


FRAGMENTOS_CONFIG = [
    ("estructura", "Estructura y campos del dataset: {}"),
    ("contexto_manual", "Contexto específico manual: {}"),
    ("analisis_contextual", "Análisis contextual del dataset: {}"),
    ("relacion_contexto", "Relación del dataset con el estudio científico: {}"),
]


def procesar_y_estructurar_indice():
    """Indexa por fragmento semántico (uno por campo relevante) en vez de un único
    documento monolítico por dataset: bge-m3 pierde precisión cuando concatena
    ideas heterogéneas (estructura, contexto manual, análisis, relación con el
    artículo) en un solo vector. Cada fragmento comparte metadata "doc_group"
    para poder reagruparse por dataset en tiempo de búsqueda.
    """
    try:
        return _procesar_y_estructurar_indice_impl()
    finally:
        _liberar_collection()


def _procesar_y_estructurar_indice_impl():
    ids_existentes = cargar_ids_desde_chroma()
    grupos_existentes = {"::".join(doc_id.split("::")[:2]) for doc_id in ids_existentes}
    print(f"📊 IDs detectados en ChromaDB actualmente: {len(ids_existentes)}")

    urls_dataverse = _cargar_urls_dataverse()

    if not RUTA_INVESTIGACIONES.exists():
        print(f"❌ La carpeta '{RUTA_INVESTIGACIONES.resolve()}' no existe.")
        return

    batch_documents = []
    batch_metadatas = []
    batch_ids = []

    for carpeta_inv in RUTA_INVESTIGACIONES.iterdir():
        if carpeta_inv.is_dir():
            ruta_json = carpeta_inv / "metadatos.json"
            if not ruta_json.exists():
                continue
                
            try:
                with open(ruta_json, "r", encoding="utf-8") as f:
                    datos_json = json.load(f)
                
                proyecto_nombre = datos_json.get("proyecto_nombre", carpeta_inv.name)
                articulos = datos_json.get("articulos", [])
                datasets = datos_json.get("datasets", [])

                # 1. Mapeamos la relación con el contexto, autores de artículos y títulos
                relaciones_por_dataset = {}
                autores_articulos_por_dataset = {}
                titulo_articulo_por_dataset = {}
                
                for art in articulos:
                    autores_art = formatear_autores(art.get("autores", []))
                    titulo_doc = art.get("titulo_documento", "").strip()
                    
                    for rel in art.get("relaciones_datasets", []):
                        nombre_ds = rel.get("nombre_dataset")
                        relacion_contexto = rel.get("relacion_con_contexto", "").strip()
                        if nombre_ds:
                            if relacion_contexto:
                                relaciones_por_dataset[nombre_ds] = relacion_contexto
                            if autores_art:
                                autores_articulos_por_dataset[nombre_ds] = autores_art
                            if titulo_doc:
                                titulo_articulo_por_dataset[nombre_ds] = titulo_doc

                # 2. Procesamos cada dataset concentrándonos SOLO en contexto y análisis
                for ds in datasets:
                    nombre_dataset = ds.get("nombre_dataset")
                    if not nombre_dataset:
                        continue

                    doc_group = f"{carpeta_inv.name}::{nombre_dataset}"
                    if doc_group in grupos_existentes:
                        continue

                    # Extraemos todos los campos que aportan valor analítico/contextual para el VECTOR
                    campos = {
                        "estructura": ds.get("explicacion_estructura", "").strip(),
                        "contexto_manual": ds.get("contexto_specifico_manual", "").strip(),
                        "analisis_contextual": ds.get("analisis_contextual", "").strip(),
                        "relacion_contexto": relaciones_por_dataset.get(nombre_dataset, "").strip(),
                    }

                    if not any(campos.values()):
                        print(f"⚠️ Omitido {nombre_dataset}: No contiene ningún campo de análisis o contexto.")
                        continue

                    # --- EXTRACCIÓN EXTRA PARA LOS METADATOS ---
                    # Extraer autores propios del dataset si existen
                    autores_ds = formatear_autores(ds.get("autores", []))
                    # Obtener autores del artículo científico asociado
                    autores_art = autores_articulos_por_dataset.get(nombre_dataset, "")
                    # Fusionamos ambos orígenes de autores de forma limpia
                    autores_finales = ", ".join(filter(None, [autores_art, autores_ds]))

                    # Obtener el título de la investigación/estudio científico
                    titulo_investigacion = titulo_articulo_por_dataset.get(nombre_dataset, "").strip()
                    if not titulo_investigacion:
                        titulo_investigacion = "No asociado a ningún artículo"

                    metadata_base = {
                        "archivo": nombre_dataset,
                        "proyecto": proyecto_nombre,
                        "investigacion": titulo_investigacion,
                        "autores": autores_finales if autores_finales else "No especificados",
                        "carpeta_origen": carpeta_inv.name,
                        "doc_group": doc_group,
                        "dataverse_url": urls_dataverse.get(doc_group, ""),
                    }

                    # Un documento (y por tanto un vector) por fragmento, en vez de
                    # concatenar todo el análisis en un único embedding.
                    for tipo_fragmento, plantilla in FRAGMENTOS_CONFIG:
                        valor = campos[tipo_fragmento]
                        if not valor:
                            continue
                        doc_id = f"{doc_group}::{tipo_fragmento}"
                        batch_documents.append(plantilla.format(valor))
                        batch_ids.append(doc_id)
                        batch_metadatas.append({**metadata_base, "tipo_fragmento": tipo_fragmento})

                    grupos_existentes.add(doc_group)
                    print(f"✨ Preparado para indexar: {doc_group}")

            except Exception as e:
                print(f"❌ Error procesando la carpeta {carpeta_inv.name}: {e}")

    # =====================================================================
    # --- 3. INSERCION MASIVA ---
    # =====================================================================
    if batch_ids:
        print(f"\n🚀 Guardando {len(batch_ids)} documentos analíticos en ChromaDB...")
        try:
            _obtener_collection().add(
                documents=batch_documents,
                metadatas=batch_metadatas,
                ids=batch_ids
            )
            print("✅ Guardado masivo completado con éxito.")
            return len(batch_ids)
        except Exception as e:
            print(f"❌ Error al insertar datos en ChromaDB: {e}")
    else:
        print("\n☕ No se encontraron nuevos datos contextuales para indexar.")