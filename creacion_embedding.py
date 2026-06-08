import os
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

print("🔄 Inicializando cliente de ChromaDB...")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

print("🧠 Cargando modelo de embeddings BAAI/bge-m3...")
embedding_bge_m3 = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-m3",
    device="cuda" if torch.cuda.is_available() else "cpu"
)

collection = chroma_client.get_or_create_collection(
    name="datasets_metadata_v3_bge", 
    embedding_function=embedding_bge_m3,
    metadata={"hnsw:space": "cosine"} 
)

# =====================================================================
# --- 2. FUNCIONES DE PROCESAMIENTO Y AUXILIARES ---
# =====================================================================

def cargar_ids_desde_chroma():
    """Recupera los IDs que ya existen en la base de datos."""
    try:
        resultado = collection.get(include=[])
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


def procesar_y_estructurar_indice():
    """Indexa extrayendo EXCLUSIVAMENTE contexto para el vector e inyectando autores en metadatos."""
    ids_existentes = cargar_ids_desde_chroma()
    print(f"📊 IDs detectados en ChromaDB actualmente: {len(ids_existentes)}")
    
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

                    doc_id = f"{carpeta_inv.name}::{nombre_dataset}"
                    if doc_id in ids_existentes:
                        continue

                    # Extraemos todos los campos que aportan valor analítico/contextual para el VECTOR
                    estructura = ds.get("explicacion_estructura", "").strip()
                    contexto_manual = ds.get("contexto_specifico_manual", "").strip()
                    analisis_contextual = ds.get("analisis_contextual", "").strip()
                    relacion_contexto = relaciones_por_dataset.get(nombre_dataset, "").strip()

                    fragmentos = []
                    if estructura:
                        fragmentos.append(f"Estructura y campos del dataset: {estructura}")
                    if contexto_manual:
                        fragmentos.append(f"Contexto específico manual: {contexto_manual}")
                    if analisis_contextual:
                        fragmentos.append(f"Análisis contextual del dataset: {analisis_contextual}")
                    if relacion_contexto:
                        fragmentos.append(f"Relación del dataset con el estudio científico: {relacion_contexto}")

                    texto_indexar = " | ".join(fragmentos)

                    if not texto_indexar.strip():
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

                    # Guardamos el bloque completo en la estructura Batch
                    batch_documents.append(texto_indexar)
                    batch_ids.append(doc_id)
                    
                    # SOLUCIÓN AQUÍ: Inyectamos los campos que la app de Streamlit va a buscar
                    batch_metadatas.append({
                        "archivo": nombre_dataset,
                        "proyecto": proyecto_nombre,
                        "investigacion": titulo_investigacion,
                        "autores": autores_finales if autores_finales else "No especificados",
                        "carpeta_origen": carpeta_inv.name
                    })
                    
                    ids_existentes.add(doc_id)
                    print(f"✨ Preparado para indexar: {doc_id}")

            except Exception as e:
                print(f"❌ Error procesando la carpeta {carpeta_inv.name}: {e}")

    # =====================================================================
    # --- 3. INSERCION MASIVA ---
    # =====================================================================
    if batch_ids:
        print(f"\n🚀 Guardando {len(batch_ids)} documentos analíticos en ChromaDB...")
        try:
            collection.add(
                documents=batch_documents,
                metadatas=batch_metadatas,
                ids=batch_ids
            )
            print("✅ Guardado masivo completado con éxito.")
        except Exception as e:
            print(f"❌ Error al insertar datos en ChromaDB: {e}")
    else:
        print("\n☕ No se encontraron nuevos datos contextuales para indexar.")


if __name__ == "__main__":
    print("=== INICIANDO PIPELINE VECTORIAL ENFOCADO EN ANÁLISIS Y CONTEXTO ===")
    procesar_y_estructurar_indice()
    print("=== PIPELINE FINALIZADO ===")