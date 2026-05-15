import os
import json
import chromadb
from pathlib import Path
from chromadb.utils import embedding_functions

# === 1. CONFIGURACIÓN ===
RUTA_INVESTIGACIONES = Path("investigaciones")
CHROMA_PATH = "chroma_db"

# Cliente y función de embedding
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
default_ef = embedding_functions.DefaultEmbeddingFunction()

# Obtener o crear la colección
collection = chroma_client.get_or_create_collection(
    name="datasets_metadata", 
    embedding_function=default_ef
)

def obtener_ids_existentes():
    """Recupera todos los IDs ya indexados para comparar."""
    try:
        # Obtenemos solo los IDs para ahorrar memoria
        existentes = collection.get(include=[])
        return set(existentes['ids'])
    except:
        return set()
