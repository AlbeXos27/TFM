import os
import json
import chromadb
import torch
from pathlib import Path
from chromadb.utils import embedding_functions
# Importamos las clases nativas de Hugging Face

# === 1. CONFIGURACIÓN ===
RUTA_INVESTIGACIONES = Path("investigaciones")
CHROMA_PATH = "chroma_db"

# Cliente y función de embedding multilingüe BGE-M3
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

embedding_bge_m3 = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-m3",
    device="cuda" if torch.cuda.is_available() else "cpu"
)

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
                    datos = json.load(f)
                
                titulo_inv = datos.get("titulo", carpeta_inv.name)
                autores = datos.get("autores", "Autores no especificados")
                contexto_general = datos.get("contexto_general", "")
                datasets = datos.get("datasets", [])

                if isinstance(autores, list):
                    autores_str = ", ".join(autores)
                else:
                    autores_str = str(autores).replace("[", "").replace("]", "").replace("'", "")

                for ds in datasets:
                    nombre_archivo = ds.get("archivo")
                    descripcion_archivo = ds.get("descripcion")

                    if not nombre_archivo or not descripcion_archivo:
                        continue

                    doc_id = f"{carpeta_inv.name}::{nombre_archivo}"

                    if doc_id in ids_existentes:
                        continue

                    texto_indexar = (
                        f"investigacion: {titulo_inv}. "
                        f"autores: {autores_str}. "
                        f"contexto general del estudio: {contexto_general}. "
                        f"archivo cientifico: {nombre_archivo}. "
                        f"descripcion especifica de este archivo: {descripcion_archivo}."
                    ).lower()

                    batch_documents.append(texto_indexar)
                    batch_ids.append(doc_id)
                    batch_metadatas.append({
                        "archivo": nombre_archivo,
                        "investigacion": titulo_inv,
                        "carpeta_origen": carpeta_inv.name,
                        "autores": autores_str[:500]
                    })
                    
                    ids_existentes.add(doc_id)
                    print(f"✨ Enriquecido y preparado para indexar: {doc_id}")

            except Exception as e:
                print(f"❌ Error procesando {carpeta_inv.name}: {e}")

    if batch_ids:
        print(f"\n🚀 Guardando {len(batch_ids)} nuevos documentos en ChromaDB de forma masiva...")
        collection.add(
            documents=batch_documents,
            metadatas=batch_metadatas,
            ids=batch_ids
        )
        print("✅ Guardado masivo completado con éxito.")
    else:
        print("\n☕ No se detectaron nuevos datasets para indexar.")

if __name__ == "__main__":
    procesar_y_estructurar_indice()
    
  