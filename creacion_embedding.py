import os
import json
import chromadb
from pathlib import Path
from chromadb.utils import embedding_functions

# === 1. CONFIGURACIÓN ===
RUTA_INVESTIGACIONES = Path("investigaciones")
CHROMA_PATH = "chroma_db"

# Cliente y función de embedding multilingüe BGE-M3
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

# Configuración del nuevo modelo BGE-M3
embedding_bge_m3 = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-m3"
)

# Cambiado el nombre a 'v3_bge' para evitar conflictos de dimensiones con el modelo anterior e5
collection = chroma_client.get_or_create_collection(
    name="datasets_metadata_v3_bge", 
    embedding_function=embedding_bge_m3,
    metadata={"hnsw:space": "cosine"} 
)


def cargar_ids_desde_chroma():
    """Recupera los IDs que ya existen en la base de datos vectorial."""
    try:
        resultado = collection.get(include=[])
        return set(resultado['ids'])
    except Exception as e:
        print(f"⚠️ No se pudo leer ChromaDB (puede estar vacía): {e}")
        return set()


def procesar_y_estructurar_indice():
    ids_existentes = cargar_ids_desde_chroma()
    print(f"📊 IDs detectados en ChromaDB actualmente: {len(ids_existentes)}")
    
    if not RUTA_INVESTIGACIONES.exists():
        print(f"❌ La carpeta '{RUTA_INVESTIGACIONES}' no existe.")
        return

    # Listas para acumular los datos y realizar una inserción masiva (Batch) al final
    batch_documents = []
    batch_metadatas = []
    batch_ids = []

    # Escanear la estructura de carpetas local
    for carpeta_inv in RUTA_INVESTIGACIONES.iterdir():
        if carpeta_inv.is_dir():
            ruta_json = carpeta_inv / "metadatos.json"
            
            if not ruta_json.exists():
                continue
                
            try:
                with open(ruta_json, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                
                titulo_inv = datos.get("titulo", carpeta_inv.name)
                datasets = datos.get("datasets", [])

                for ds in datasets:
                    nombre_archivo = ds.get("archivo")
                    descripcion = ds.get("descripcion")

                    if not nombre_archivo or not descripcion:
                        continue

                    # Identificador único estándar
                    doc_id = f"{carpeta_inv.name}::{nombre_archivo}"

                    # Evitamos procesar si ya existe en la base de datos
                    if doc_id in ids_existentes:
                        continue

                    # Enriquecemos levemente el texto para que el embedding entienda el contexto global
                    # Convertir a minúsculas ayuda a estandarizar la entrada semántica
                    texto_indexar = f"investigacion: {titulo_inv}. archivo: {nombre_archivo}. descripcion: {descripcion}".lower()

                    # Añadimos los elementos a las listas de procesamiento masivo
                    batch_documents.append(texto_indexar)
                    batch_ids.append(doc_id)
                    batch_metadatas.append({
                        "archivo": nombre_archivo,
                        "investigacion": titulo_inv,
                        "carpeta_origen": carpeta_inv.name
                    })
                    
                    # Añadimos al set local en memoria para evitar duplicados en el mismo loop
                    ids_existentes.add(doc_id)
                    print(f"✨ Preparado para indexar: {doc_id}")

            except Exception as e:
                print(f"❌ Error procesando {carpeta_inv.name}: {e}")

    # Realizar el guardado en bloque (Batch) si se encontraron nuevos elementos
    if batch_ids:
        print(f"🚀 Guardando {len(batch_ids)} nuevos documentos en ChromaDB de forma masiva...")
        collection.add(
            documents=batch_documents,
            metadatas=batch_metadatas,
            ids=batch_ids
        )
        print("✅ Guardado masivo completado con éxito.")
    else:
        print("☕ No se detectaron nuevos datasets para indexar.")


if __name__ == "__main__":
    procesar_y_estructurar_indice()
    
    print("\n🔍 Ejecutando query de prueba...")
    # Buscamos pasando el texto en minúsculas para mantener simetría con el índice
    query_usuario = "datasets con diálogos para entrenar chatbots de inteligencia artificial"
    resultado_busqueda = collection.query(query_texts=[query_usuario.lower()], n_results=1)
    print(resultado_busqueda)