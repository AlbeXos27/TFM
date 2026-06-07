import os
import json
import chromadb
import torch
from pathlib import Path
from chromadb.utils import embedding_functions

# =====================================================================
# --- 1. CONFIGURACIÓN DE RUTAS Y MODELOS ---
# =====================================================================
# Carpeta raíz donde tu Streamlit guarda los proyectos/combinaciones
RUTA_INVESTIGACIONES = Path("investigaciones")
CHROMA_PATH = "chroma_db"

print("🔄 Inicializando cliente de ChromaDB...")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

# Configuración del modelo embedding multilingüe BGE-M3
print("🧠 Cargando modelo de embeddings BAAI/bge-m3...")
embedding_bge_m3 = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-m3",
    device="cuda" if torch.cuda.is_available() else "cpu"
)

# Obtener o crear la colección con métrica de distancia coseno
collection = chroma_client.get_or_create_collection(
    name="datasets_metadata_v3_bge", 
    embedding_function=embedding_bge_m3,
    metadata={"hnsw:space": "cosine"} 
)


# =====================================================================
# --- 2. FUNCIONES DE PROCESAMIENTO ---
# =====================================================================

def cargar_ids_desde_chroma():
    """Recupera de forma segura los IDs que ya existen en la base de datos."""
    try:
        resultado = collection.get(include=[])
        return set(resultado['ids'])
    except Exception as e:
        print(f"⚠️ No se pudo leer ChromaDB (puede estar vacía o inicializándose): {e}")
        return set()


def procesar_y_estructurar_indice():
    """Escanea la carpeta de investigaciones, procesa los JSON de Streamlit e indexa."""
    ids_existentes = cargar_ids_desde_chroma()
    print(f"📊 IDs detectados en ChromaDB actualmente: {len(ids_existentes)}")
    
    if not RUTA_INVESTIGACIONES.exists():
        print(f"❌ La carpeta '{RUTA_INVESTIGACIONES.resolve()}' no existe en el directorio actual.")
        print("💡 Asegúrate de ejecutar este script desde la raíz o de que Streamlit haya creado carpetas dentro de 'investigaciones'.")
        return

    # Listas para la inserción masiva (Batch)
    batch_documents = []
    batch_metadatas = []
    batch_ids = []

    # Iterar sobre cada subcarpeta generada (cada "proyecto" o "combinación")
    for carpeta_inv in RUTA_INVESTIGACIONES.iterdir():
        if carpeta_inv.is_dir():
            ruta_json = carpeta_inv / "metadatos.json"
            if not ruta_json.exists():
                continue
                
            try:
                with open(ruta_json, "r", encoding="utf-8") as f:
                    datos_json = json.load(f)
                
                # Accedemos a la lista de "articulos" que genera tu app de Streamlit
                articulos = datos_json.get("articulos", [])

                for articulo in articulos:
                    titulo_inv = articulo.get("titulo", carpeta_inv.name)
                    contexto_general = articulo.get("contexto_unico", "")
                    
                    # 👥 Formateo avanzado de autores unificando Nombre + ORCID
                    autores_lista = articulo.get("autores", [])
                    autores_formateados = []
                    for a in autores_lista:
                        nombre_autor = a.get("nombre", "").strip()
                        orcid_autor = a.get("orcid", "").strip()
                        if orcid_autor:
                            autores_formateados.append(f"{nombre_autor} (orcid: {orcid_autor})")
                        elif nombre_autor:
                            autores_formateados.append(nombre_autor)
                    
                    autores_str = ", ".join(autores_formateados)

                    # 📊 Iterar por las relaciones de los datasets adjuntos a este artículo
                    datasets_vinculados = articulo.get("relaciones_datasets", [])

                    for ds in datasets_vinculados:
                        nombre_archivo = ds.get("archivo_dataset")
                        descripcion_archivo = ds.get("relacion_con_contexto")

                        if not nombre_archivo or not descripcion_archivo:
                            continue

                        # Generamos un ID único combinando la carpeta origen y el dataset
                        doc_id = f"{carpeta_inv.name}::{nombre_archivo}"

                        # Evitar duplicados si el archivo ya fue indexado previamente
                        if doc_id in ids_existentes:
                            continue

                        # 📝 Construcción del texto semántico completo (Normalizado a minúsculas)
                        texto_indexar = (
                            f"investigacion: {titulo_inv}. "
                            f"autores: {autores_str}. "
                            f"contexto general del estudio: {contexto_general}. "
                            f"archivo cientifico: {nombre_archivo}. "
                            f"descripcion especifica de este archivo: {descripcion_archivo}."
                        ).lower()

                        # Almacenar en los arreglos temporales del Batch
                        batch_documents.append(texto_indexar)
                        batch_ids.append(doc_id)
                        batch_metadatas.append({
                            "archivo": nombre_archivo,
                            "investigacion": titulo_inv,
                            "carpeta_origen": carpeta_inv.name,
                            "autores": autores_str[:500]  # Control de longitud máxima en metadatos
                        })
                        
                        # Añadir al set local para evitar colisiones en el mismo bucle
                        ids_existentes.add(doc_id)
                        print(f"✨ Enriquecido y preparado para indexar: {doc_id}")

            except Exception as e:
                print(f"❌ Error crítico procesando la carpeta {carpeta_inv.name}: {e}")

    # =====================================================================
    # --- 3. INSERCIÓN MASIVA A CHROMADB ---
    # =====================================================================
    if batch_ids:
        print(f"\n🚀 Guardando {len(batch_ids)} nuevos documentos en ChromaDB de forma masiva...")
        try:
            collection.add(
                documents=batch_documents,
                metadatas=batch_metadatas,
                ids=batch_ids
            )
            print("✅ Guardado masivo completado con éxito. Datos listos para producción.")
        except Exception as e:
            print(f"❌ Error al insertar datos en ChromaDB: {e}")
    else:
        print("\n☕ No se detectaron nuevos datasets o estructuras JSON inéditas para indexar.")


if __name__ == "__main__":
    print("=== INICIANDO PIPELINE DE INDEXACIÓN VECTORIAL ===")
    procesar_y_estructurar_indice()
    print("=== PIPELINE FINALIZADO ===")