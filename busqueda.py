import os
import json
import chromadb
import torch
import streamlit as st

from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from groq import Groq 

# =========================================================
# CONFIG STREAMLIT Y CONFIGURACIONES FIJAS
# =========================================================
st.set_page_config(page_title="Buscador SIEGMA-LLM", page_icon="🔬", layout="wide")
os.environ["TOKENIZERS_PARALLELISM"] = "false"
device = "cuda" if torch.cuda.is_available() else "cpu"

UMBRAL_RERANK_FIJO = -2.0 
API_KEY_GROQ = st.secrets["API_KEY_GROQ"]
MODELO_LLM = st.secrets["MODELO_LLM"]

client_groq = Groq(api_key=API_KEY_GROQ)

# =========================================================
# CARGA PERSISTENTE DE MODELOS
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
# MAPEO DINÁMICO CON GROQ
# =========================================================
def mapear_conceptos_dinamico_con_groq(query_usuario):
    messages = [
        {
            "role": "system",
            "content": "Eres un backend de IA que SOLO devuelve JSON. Tu única tarea es devolver palabras clave científicas relacionadas en español."
        },
        {
            "role": "user",
            "content": f"""Genera de 5 a 8 términos científicos o sinónimos relacionados con: "{query_usuario}".
            
            Debes responder ESTRICTAMENTE con este formato JSON:
            {{"conceptos_relacionados": "termino1, termino2, termino3"}}
            
            No incluyas introducciones ni explicaciones."""
        }
    ]
    try:
        completion = client_groq.chat.completions.create(
            model=MODELO_LLM, 
            messages=messages,
            temperature=0.1, 
            response_format={"type": "json_object"},
            max_tokens=100
        )
        
        texto_respuesta = completion.choices[0].message.content
        datos_json = json.loads(texto_respuesta)
        conceptos = datos_json.get("conceptos_relacionados", "")
        
        lista_conceptos = [c.strip() for c in conceptos.split(",") if c.strip()]
        
        if lista_conceptos and "".join(lista_conceptos).lower() != query_usuario.lower().strip():
            return lista_conceptos, None
        return [], None
    except Exception as e:
        return [], str(e)

# =========================================================
# LÓGICA DE BÚSQUEDA ADAPTADA (Filtro Híbrido Avanzado)
# =========================================================
def buscar(query_usuario, top_k=15):
    lista_conceptos, error_groq = mapear_conceptos_dinamico_con_groq(query_usuario)
    
    # 1. Creamos la query enriquecida SOLO para la primera fase (ChromaDB)
    if lista_conceptos:
        conceptos_str = " ".join(lista_conceptos)
        query_enriquecida = f"{query_usuario} {conceptos_str}"
    else:
        query_enriquecida = query_usuario
    
    # Búsqueda en ChromaDB con el espectro ampliado
    query_embedding = embedding_model.encode(query_enriquecida, normalize_embeddings=True, convert_to_numpy=True).tolist()
    resultado_chroma = collection.query(query_embeddings=[query_embedding], n_results=top_k)
    
    docs = resultado_chroma["documents"][0]
    if not docs: 
        return [], query_enriquecida, lista_conceptos, error_groq
    
    # 2. FASE ADAPTADA: Evaluamos el re-ranking usando la query_usuario ORIGINAL
    pares = [[query_usuario, doc] for doc in docs]
    inputs = tokenizer_rerank(pares, padding=True, truncation=True, max_length=1024, return_tensors="pt").to(device)
    
    with torch.no_grad():
        scores = model_rerank(**inputs).logits.view(-1).float().cpu().tolist()
    
    resultados_filtrados = [
        (resultado_chroma["ids"][0][i], docs[i], resultado_chroma["metadatas"][0][i], scores[i])
        for i, score in enumerate(scores) if score >= UMBRAL_RERANK_FIJO
    ]
    return sorted(resultados_filtrados, key=lambda x: x[3], reverse=True), query_enriquecida, lista_conceptos, error_groq

# =========================================================
# INTERFAZ DE USUARIO
# =========================================================
st.title("Buscador")

with st.sidebar:
    top_k = st.slider("Candidatos iniciales", 5, 50, 15) # Recomendado subirlo un poco para capturar más sinónimos
    st.caption(f"Filtro Reranker: Score >= {UMBRAL_RERANK_FIJO}")

query = st.text_input("💬 Introduce tu consulta", placeholder="Ej: dataset de salinidad...")

if st.button("🔍 Buscar en el repositorio", type="primary"):
    if not query.strip():
        st.warning("Por favor, escribe algo antes de buscar.")
    else:
        with st.spinner("Buscando candidatos y aplicando Reranking estricto..."):
            resultados, query_usada, conceptos_extra, error_api = buscar(query, top_k=top_k)
            
        # --- PANEL DE CONTROL SEMÁNTICO ---
        if error_api:
            st.error(f"❌ Error al conectar con Groq: `{error_api}`")
        elif conceptos_extra:
            st.write("### Sinónimos usados en la pre-búsqueda")
            st.pills("Conceptos detectados", conceptos_extra, disabled=True)
            st.write("---")
        else:
            st.warning("⚠️ No se generaron conceptos extras. Búsqueda directa ejecutada.")

        # --- SECCIÓN DE RESULTADOS ---
        if not resultados:
            st.error("No se encontraron resultados que superen el umbral de calidad del Reranker.")
        else:
            st.success(f"✅ Se encontraron {len(resultados)} resultados ordenados por relevancia directa.")
            for i, (id_doc, doc, meta, score) in enumerate(resultados, 1):
                with st.expander(f"✨ #{i} — {meta.get('archivo', 'Archivo')} (Relevancia: {score:.2f})"):
                    st.write(f"**Investigación:** {meta.get('investigacion', 'N/A')}")
                    st.write(f"**Autores:** {meta.get('autores', 'N/A')}")
                    st.text_area("Análisis:", value=doc, height=100, disabled=True, key=f"t_{id_doc}")