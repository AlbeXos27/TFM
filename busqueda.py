import os
import json
import chromadb
import torch
import streamlit as st

from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForSequenceClassification
# Importación del SDK oficial de Groq
from groq import Groq 

# =========================================================
# CONFIG STREAMLIT Y CONFIGURACIONES FIJAS
# =========================================================
st.set_page_config(page_title="Buscador Científico IA", page_icon="🔬", layout="wide")
os.environ["TOKENIZERS_PARALLELISM"] = "false"
device = "cuda" if torch.cuda.is_available() else "cpu"

# Configuraciones estrictas solicitadas
UMBRAL_RERANK_FIJO = -2.0 
API_KEY_GROQ = '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'
MODELO_LLM = "meta-llama/llama-4-scout-17b-16e-instruct"

# Inicialización del cliente de Groq
client_groq = Groq(api_key=API_KEY_GROQ)

# =========================================================
# CARGA PERSISTENTE DE MODELOS EN CACHÉ
# =========================================================
@st.cache_resource
def cargar_embedding_model():
    return SentenceTransformer("BAAI/bge-m3", device=device)

@st.cache_resource
def cargar_reranker():
    modelo_reranker_name = "BAAI/bge-reranker-v2-m3"
    tokenizer = AutoTokenizer.from_pretrained(modelo_reranker_name)
    model = AutoModelForSequenceClassification.from_pretrained(modelo_reranker_name)
    model.to(device).eval()
    return tokenizer, model

@st.cache_resource
def cargar_chroma():
    chroma_client = chromadb.PersistentClient(path="chroma_db")
    return chroma_client.get_or_create_collection(
        name="datasets_metadata_v3_bge",
        metadata={"hnsw:space": "cosine"}
    )

with st.spinner("⏳ Cargando modelos IA en memoria..."):
    embedding_model = cargar_embedding_model()
    tokenizer_rerank, model_rerank = cargar_reranker()
    collection = cargar_chroma()

# =========================================================
# 🌟 MAPEO DINÁMICO EN JSON GENERADO POR EL LLM (GROQ)
# =========================================================
def mapear_conceptos_dinamico_con_groq(query_usuario):
    """
    Obliga a Groq a pensar en el entorno de la consulta y 
    devolver un JSON estructurado en tiempo real con conceptos asociados.
    """
    prompt = f"""
    Actúa como un científico enciclopedista. Tu trabajo es analizar la consulta del usuario y generar un mapa de conceptos, sinónimos, entornos del mundo real, variables y contextos lógicos relacionados.
    Debes devolver la respuesta estrictamente en formato JSON con la estructura del siguiente ejemplo.

    EJEMPLO DE SALIDA DEBERÍA SER ASÍ (SÓLO EL JSON):
    {{
        "conceptos_relacionados": "mar, océano, agua marina, profundidad, conductividad eléctrica, ciencias del mar, boyas, sal, densidad"
    }}

    Consulta del usuario actual: "{query_usuario}"
    Respuesta (devuelve EXCLUSIVAMENTE el JSON estructurado, sin introducciones ni marcas de markdown):
    """
    try:
        completion = client_groq.chat.completions.create(
            model=MODELO_LLM, 
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,  # Margen controlado para que asocie de forma inteligente
            max_tokens=100
        )
        
        # Limpieza básica por si el modelo añade bloques de código de markdown
        respuesta_texto = completion.choices[0].message.content.strip()
        if respuesta_texto.startswith("```json"):
            respuesta_texto = respuesta_texto.split("```json")[1].split("```")[0].strip()
        elif respuesta_texto.startswith("```"):
            respuesta_texto = respuesta_texto.split("```")[1].split("```")[0].strip()

        # Decodificamos el JSON que el LLM acaba de inventar en caliente
        datos_json = json.loads(respuesta_texto)
        return datos_json.get("conceptos_relacionados", "")
        
    except Exception as e:
        # Si el LLM falla, no rompemos la app, devolvemos vacío y buscamos normal
        return ""

# =========================================================
# LÓGICA DE BÚSQUEDA FILTRADA (CORTE INTERNO EN -2.0)
# =========================================================
def buscar(query_usuario, top_k=15):
    # 1. El LLM genera el mapeo de conceptos en formato JSON internamente en tiempo real
    with st.spinner("🤖 Groq está creando el mapa de conceptos en JSON..."):
        conceptos_entorno = mapear_conceptos_dinamico_con_groq(query_usuario)
    
    if conceptos_entorno:
        # Creamos la súper consulta inyectando lo que el LLM descubrió
        query_enriquecida = f"{query_usuario} | Contexto y palabras relacionadas: {conceptos_entorno}"
        st.info(f"💡 **Expansión generada por Groq en vivo:** *{query_enriquecida}*")
    else:
        query_enriquecida = query_usuario
    
    # 2. Conversión a Embedding
    query_embedding = embedding_model.encode(
        query_enriquecida, 
        normalize_embeddings=True, 
        convert_to_numpy=True, 
        show_progress_bar=False
    ).tolist()
    
    # 3. Recuperación en ChromaDB
    resultado_chroma = collection.query(query_embeddings=[query_embedding], n_results=top_k)
    
    ids_candidatos = resultado_chroma["ids"][0] if resultado_chroma["ids"] else []
    documentos_candidatos = resultado_chroma["documents"][0] if resultado_chroma["documents"] else []
    metadatas_candidatos = resultado_chroma["metadatas"][0] if resultado_chroma["metadatas"] else []
    distancias_chroma = resultado_chroma["distances"][0] if resultado_chroma["distances"] else []
    
    if not documentos_candidatos:
        return []
    
    # 4. Reranking (Evaluación contra la consulta ORIGINAL del usuario)
    pares = [[query_usuario, doc] for doc in documentos_candidatos]
    inputs = tokenizer_rerank(pares, padding=True, truncation=True, max_length=1024, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    
    with torch.no_grad():
        scores = model_rerank(**inputs).logits.view(-1).float().cpu().tolist()
    
    # 5. Filtrar por el umbral rígido oculto de -2.0
    resultados_filtrados = []
    for id_doc, doc, meta, dist, score in zip(ids_candidatos, documentos_candidatos, metadatas_candidatos, distancias_chroma, scores):
        if score >= UMBRAL_RERANK_FIJO:
            resultados_filtrados.append((id_doc, doc, meta, dist, score))
            
    return sorted(resultados_filtrados, key=lambda x: x[4], reverse=True)

# =========================================================
# INTERFAZ DE USUARIO (UI)
# =========================================================
st.title("🔬 Buscador Científico Inteligente")
st.caption("Pipeline RAG Avanzado: Mapeo JSON por Groq en Tiempo Real + BGE Reranker")

with st.sidebar:
    st.header("⚙️ Configuración")
    top_k = st.slider("Candidatos iniciales (Chroma)", min_value=5, max_value=50, value=15)
    st.divider()
    st.caption("🔒 **Filtro de Calidad Activo:** Los resultados irrelevantes (Score < -2.0) se descartan automáticamente.")

query = st.text_input("💬 Introduce tu consulta", placeholder="Ej: dataset de salinidad...")

if st.button("🔍 Buscar en el repositorio", type="primary"):
    if not query.strip():
        st.warning("Por favor, escribe algo antes de buscar.")
    else:
        resultados = buscar(query, top_k=top_k)
            
        if not resultados:
            st.error(f"❌ Ningún documento en la base de datos superó el filtro de calidad mínimo requerido para mostrarse (Umbral: {UMBRAL_RERANK_FIJO}).")
        else:
            st.success(f"✅ Resultados encontrados y validados por el sistema.")
            
            for i, resultado in enumerate(resultados, start=1):
                id_doc, documento, metadata, distancia, score = resultado
                
                with st.expander(f"✨ #{i} — {metadata.get('archivo', 'Archivo')} [Proyecto: {metadata.get('proyecto', 'No especificado')}]"):
                    col1, col2 = st.columns(2)
                    col1.metric(label="🔥 Score de Relevancia (Reranker)", value=f"{score:.4f}")
                    col2.metric(label="📐 Distancia Coseno (Chroma)", value=f"{distancia:.4f}")
                    
                    st.divider()
                    st.markdown("### 📂 Información Básica Extraída")
                    st.write(f"**🔬 Artículo Científico:** {metadata.get('investigacion', 'No especificada')}")
                    st.write(f"**👥 Autores:** {metadata.get('autores', 'No especificados')}")
                    
                    st.divider()
                    st.markdown("### 📄 Contexto Semántico del Dataset")
                    st.text_area(label="Bloque de Análisis Indexado", value=documento, height=120, disabled=True, key=f"t_{id_doc}_{i}")