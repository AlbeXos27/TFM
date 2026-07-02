import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import chromadb
import torch
import streamlit as st
from groq import Groq
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# =========================================================
# CONFIG STREAMLIT Y CONFIGURACIONES FIJAS
# =========================================================
st.set_page_config(page_title="Buscador SIEGMA-LLM", page_icon="🔬", layout="wide")
os.environ["TOKENIZERS_PARALLELISM"] = "false"
device = "cuda" if torch.cuda.is_available() else "cpu"

UMBRAL_RERANK_FIJO = -2.0
ALPHA_BASE = 0.7
BETA_EXP = 0.3
BOOST_POR_CONCEPTO = 0.25
MAX_CONCEPTS = 5
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
def _normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _clean_conceptos(conceptos_raw: str, query_usuario: str) -> List[str]:
    criterios = []
    for item in conceptos_raw.split(","):
        concepto = item.strip()
        if not concepto:
            continue
        if len(concepto) < 3:
            continue
        if concepto.lower() == query_usuario.lower().strip():
            continue
        criterios.append(concepto)
    unique = []
    seen = set()
    for concepto in criterios:
        key = _normalize_text(concepto)
        if key not in seen:
            seen.add(key)
            unique.append(concepto)
        if len(unique) >= MAX_CONCEPTS:
            break
    return unique


def mapear_conceptos_dinamico_con_groq(query_usuario: str) -> Tuple[List[str], Optional[str]]:
    messages = [
        {
            "role": "system",
            "content": (
                "Eres un backend de IA que SOLO devuelve JSON. "
                "Tu única tarea es devolver palabras clave científicas relacionadas en español."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Genera de 3 a 5 términos científicos o sinónimos relacionados con: \"{query_usuario}\". "
                "Debes responder ESTRICTAMENTE con este formato JSON: "
                "{\"conceptos_relacionados\": \"termino1, termino2, termino3\"}. "
                "No incluyas introducciones ni explicaciones."
            ),
        },
    ]

    try:
        completion = client_groq.chat.completions.create(
            model=MODELO_LLM,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=100,
        )
        texto_respuesta = completion.choices[0].message.content
        datos_json = json.loads(texto_respuesta)
        conceptos = datos_json.get("conceptos_relacionados", "")
        lista_conceptos = _clean_conceptos(conceptos, query_usuario)
        return lista_conceptos, None
    except Exception as e:
        return [], str(e)

# =========================================================
# LÓGICA DE BÚSQUEDA ADAPTADA (Filtro Híbrido Avanzado)
# =========================================================
def _score_combined(base_score: float, exp_score: float) -> float:
    return ALPHA_BASE * base_score + BETA_EXP * exp_score


def _merge_results(
    base_results: Dict[str, Dict[str, Any]],
    exp_results_list: List[Dict[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for doc_id, item in base_results.items():
        merged[doc_id] = {
            "id": doc_id,
            "document": item["document"],
            "metadata": item["metadata"],
            "score_base": item["score"],
            "score_exp": 0.0,
            "concept_hits": 0,
        }

    for exp_results in exp_results_list:
        for doc_id, item in exp_results.items():
            if doc_id not in merged:
                merged[doc_id] = {
                    "id": doc_id,
                    "document": item["document"],
                    "metadata": item["metadata"],
                    "score_base": 0.0,
                    "score_exp": 0.0,
                    "concept_hits": 0,
                }
            merged[doc_id]["score_exp"] += item["score"]
            merged[doc_id]["concept_hits"] += 1

    combined = []
    for item in merged.values():
        if item["concept_hits"] > 0:
            item["score_exp"] /= item["concept_hits"]
        item["score_final"] = _score_combined(item["score_base"], item["score_exp"])
        item["score_final"] += item["concept_hits"] * BOOST_POR_CONCEPTO
        combined.append(item)

    return sorted(combined, key=lambda x: x["score_final"], reverse=True)


def _collect_chroma_results(chroma_response: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    documents = chroma_response.get("documents", [[]])[0]
    ids = chroma_response.get("ids", [[]])[0]
    metadatas = chroma_response.get("metadatas", [[]])[0]
    distances = chroma_response.get("distances", [[]])[0]

    results = {}
    for idx, doc_id in enumerate(ids):
        results[doc_id] = {
            "document": documents[idx],
            "metadata": metadatas[idx],
            "score": 1.0 - distances[idx] if distances else 0.0,
        }
    return results


def _query_concept_embeddings(conceptos: List[str], top_k: int) -> List[Dict[str, Dict[str, Any]]]:
    results = []
    for concepto in conceptos:
        embedding_concepto = embedding_model.encode(concepto, normalize_embeddings=True, convert_to_numpy=True)
        resultado_concepto = collection.query(
            query_embeddings=[embedding_concepto.tolist()],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        results.append(_collect_chroma_results(resultado_concepto))
    return results


def buscar(query_usuario, top_k=15):
    lista_conceptos, error_groq = mapear_conceptos_dinamico_con_groq(query_usuario)
    embedding_query = embedding_model.encode(query_usuario, normalize_embeddings=True, convert_to_numpy=True)

    # búsqueda base con la query original
    resultado_base = collection.query(
        query_embeddings=[embedding_query.tolist()],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    base_results = _collect_chroma_results(resultado_base)

    # búsquedas separadas para cada concepto generado
    exp_results_list: List[Dict[str, Dict[str, Any]]] = []
    if lista_conceptos:
        exp_results_list = _query_concept_embeddings(lista_conceptos, top_k)

    if not base_results and not exp_results_list:
        return [], query_usuario, lista_conceptos, error_groq

    combined_results = _merge_results(base_results, exp_results_list)
    final_candidates = []
    for doc in combined_results[:top_k]:
        final_candidates.append((doc["id"], doc["document"], doc["metadata"], doc["score_final"]))

    # reranking sobre el top combinado
    documentos = [item[1] for item in final_candidates]
    ids = [item[0] for item in final_candidates]
    metadatas = [item[2] for item in final_candidates]
    pares = [[query_usuario, documento] for documento in documentos]
    inputs = tokenizer_rerank(pares, padding=True, truncation=True, max_length=1024, return_tensors="pt").to(device)

    with torch.no_grad():
        scores = model_rerank(**inputs).logits.view(-1).float().cpu().tolist()

    reranked = [
        (ids[i], documentos[i], metadatas[i], scores[i])
        for i, score in enumerate(scores)
        if score >= UMBRAL_RERANK_FIJO
    ]
    return sorted(reranked, key=lambda x: x[3], reverse=True), query_usuario, lista_conceptos, error_groq

# =========================================================
# INTERFAZ DE USUARIO
# =========================================================
st.title("Buscador")

with st.sidebar:
    top_k = st.slider("Candidatos iniciales", 5, 50, 10) # Recomendado subirlo un poco para capturar más sinónimos
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