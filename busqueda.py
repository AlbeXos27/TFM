import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import chromadb
import ollama
import torch
import streamlit as st
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# =========================================================
# CONFIG STREAMLIT Y CONFIGURACIONES FIJAS
# =========================================================
st.set_page_config(page_title="Buscador SIEGMA-LLM", page_icon="🔬", layout="wide")
device = "cpu"
UMBRAL_RERANK_FIJO = -2.0
ALPHA_BASE = 0.7
BETA_EXP = 0.3
BOOST_POR_CONCEPTO = 0.25
MAX_CONCEPTS = 6
MODELO_LLM = "qwen3.5:4b"

# =========================================================
# CARGA PERSISTENTE DE MODELOS
# =========================================================
@st.cache_resource
def cargar_embedding_model():
    return SentenceTransformer("BAAI/bge-m3", device="cpu")

@st.cache_resource
def cargar_reranker():
    modelo_reranker_name = "BAAI/bge-reranker-v2-m3"
    tokenizer = AutoTokenizer.from_pretrained(modelo_reranker_name)
    model = AutoModelForSequenceClassification.from_pretrained(modelo_reranker_name)
    model.to("cpu").eval()
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
                "Tu única tarea es expandir una consulta de búsqueda científica en "
                "términos que maximicen el recall semántico contra un índice de "
                "datasets y artículos de investigación."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Consulta del usuario: \"{query_usuario}\". "
                "Genera de 4 a 6 términos de búsqueda relacionados combinando estas tres categorías "
                "(no los etiquetes, solo devuélvelos mezclados en la lista):\n"
                "1. Sinónimos o variantes en español del concepto principal.\n"
                "2. Equivalentes técnicos en inglés (la literatura científica suele usar terminología "
                "en inglés aunque la consulta esté en español).\n"
                "3. Sub-conceptos que descompongan la consulta en sus partes clave: la variable o "
                "fenómeno medido, el método o técnica implicado, y el contexto o dominio de aplicación.\n"
                "Sé específico y evita términos genéricos que ya estén implícitos en la consulta original. "
                "Debes responder ESTRICTAMENTE con este formato JSON: "
                "{\"conceptos_relacionados\": \"termino1, termino2, termino3, termino4\"}. "
                "No incluyas introducciones, explicaciones ni etiquetas de categoría."
            ),
        },
    ]

    try:
        completion = ollama.chat(
            model=MODELO_LLM,
            messages=messages,
            format="json",
            options={"temperature": 0.1},
            think=False,
        )
        texto_respuesta = completion["message"]["content"]
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
    """Agrupa los fragmentos devueltos por Chroma en un único resultado por dataset
    (metadata "doc_group"), ya que cada dataset se indexa como varios vectores
    (estructura, contexto manual, análisis, relación). Se queda con el mejor score
    de fragmento y concatena los textos únicos para dar contexto completo al reranker.
    """
    documents = chroma_response.get("documents", [[]])[0]
    ids = chroma_response.get("ids", [[]])[0]
    metadatas = chroma_response.get("metadatas", [[]])[0]
    distances = chroma_response.get("distances", [[]])[0]

    results: Dict[str, Dict[str, Any]] = {}
    for idx, doc_id in enumerate(ids):
        metadata = metadatas[idx]
        doc_group = metadata.get("doc_group", doc_id)
        score = 1.0 - distances[idx] if distances else 0.0

        if doc_group not in results:
            results[doc_group] = {
                "document": documents[idx],
                "metadata": metadata,
                "score": score,
                "_fragmentos_vistos": {documents[idx]},
            }
        else:
            item = results[doc_group]
            if documents[idx] not in item["_fragmentos_vistos"]:
                item["document"] = item["document"] + "\n" + documents[idx]
                item["_fragmentos_vistos"].add(documents[idx])
            if score > item["score"]:
                item["score"] = score

    for item in results.values():
        item.pop("_fragmentos_vistos", None)
    return results


# Cada dataset se indexa como hasta 4 fragmentos (vectores) independientes, así
# que para conservar ~top_k datasets únicos hay que pedir más vectores en bruto.
FRAGMENTOS_POR_DATASET = 4


def _query_concept_embeddings(conceptos: List[str], top_k: int) -> List[Dict[str, Dict[str, Any]]]:
    n_results = top_k * FRAGMENTOS_POR_DATASET
    results = []
    for concepto in conceptos:
        embedding_concepto = embedding_model.encode(concepto, normalize_embeddings=True, convert_to_numpy=True)
        resultado_concepto = collection.query(
            query_embeddings=[embedding_concepto.tolist()],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        results.append(_collect_chroma_results(resultado_concepto))
    return results


def buscar(query_usuario, top_k=15, umbral_rerank=UMBRAL_RERANK_FIJO):
    lista_conceptos, error_groq = mapear_conceptos_dinamico_con_groq(query_usuario)
    embedding_query = embedding_model.encode(query_usuario, normalize_embeddings=True, convert_to_numpy=True)

    # búsqueda base con la query original (se piden más vectores en bruto porque
    # cada dataset puede aportar varios fragmentos)
    resultado_base = collection.query(
        query_embeddings=[embedding_query.tolist()],
        n_results=top_k * FRAGMENTOS_POR_DATASET,
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

    todos_reranked = sorted(
        (
            (ids[i], documentos[i], metadatas[i], score)
            for i, score in enumerate(scores)
        ),
        key=lambda x: x[3],
        reverse=True,
    )

    reranked = [item for item in todos_reranked if item[3] >= umbral_rerank]

    # Si nada supera el umbral (consulta muy específica o corpus pequeño), no
    # devolvemos vacío sin más: se enseñan los mejores candidatos disponibles
    # marcados como de baja confianza, para que el usuario decida.
    baja_confianza = False
    if not reranked and todos_reranked:
        reranked = todos_reranked[:3]
        baja_confianza = True

    return reranked, query_usuario, lista_conceptos, error_groq, baja_confianza


def score_a_relevancia_pct(score: float) -> float:
    """Convierte el logit del reranker a un % de relevancia (0-100) más legible que
    el logit crudo, vía sigmoide. Solo para mostrar en la UI, no cambia el orden."""
    return 100.0 / (1.0 + math.exp(-score))

# =========================================================
# INTERFAZ DE USUARIO
# =========================================================
st.title("Buscador")

with st.sidebar:
    top_k = st.slider("Candidatos iniciales", 5, 50, 10) # Recomendado subirlo un poco para capturar más sinónimos
    umbral_rerank = st.slider(
        "Umbral de calidad del Reranker",
        -6.0, 4.0, UMBRAL_RERANK_FIJO, 0.5,
        help="Score mínimo del reranker (logit) para considerar un resultado relevante. "
             "Más alto = más estricto (menos falsos positivos, más falsos negativos).",
    )

query = st.text_input("💬 Introduce tu consulta", placeholder="Ej: dataset de salinidad...")

if st.button("🔍 Buscar en el repositorio", type="primary"):
    if not query.strip():
        st.warning("Por favor, escribe algo antes de buscar.")
    else:
        with st.spinner("Buscando candidatos y aplicando Reranking estricto..."):
            resultados, query_usada, conceptos_extra, error_api, baja_confianza = buscar(
                query, top_k=top_k, umbral_rerank=umbral_rerank
            )

        # --- PANEL DE CONTROL SEMÁNTICO ---
        if error_api:
            st.error(f"❌ Error al conectar con Ollama: `{error_api}`")
        elif conceptos_extra:
            st.write("### Sinónimos usados en la pre-búsqueda")
            st.pills("Conceptos detectados", conceptos_extra, disabled=True)
            st.write("---")
        else:
            st.warning("⚠️ No se generaron conceptos extras. Búsqueda directa ejecutada.")

        # --- SECCIÓN DE RESULTADOS ---
        if not resultados:
            st.error("No se encontraron resultados ni siquiera de baja confianza. Prueba a reformular la consulta.")
        else:
            if baja_confianza:
                st.warning(
                    "⚠️ Ningún resultado superó el umbral de calidad. Se muestran los mejores "
                    "candidatos disponibles, pero su relevancia no está garantizada."
                )
            else:
                st.success(f"✅ Se encontraron {len(resultados)} resultados ordenados por relevancia directa.")
            for i, (id_doc, doc, meta, score) in enumerate(resultados, 1):
                relevancia_pct = score_a_relevancia_pct(score)
                etiqueta_confianza = " · baja confianza" if baja_confianza else ""
                with st.expander(
                    f"✨ #{i} — {meta.get('archivo', 'Archivo')} "
                    f"(Relevancia: {relevancia_pct:.0f}%{etiqueta_confianza})"
                ):
                    st.write(f"**Investigación:** {meta.get('investigacion', 'N/A')}")
                    st.write(f"**Autores:** {meta.get('autores', 'N/A')}")
                    st.text_area("Análisis:", value=doc, height=100, disabled=True, key=f"t_{id_doc}")

                    url_dataverse = meta.get("dataverse_url", "")
                    if url_dataverse:
                        st.link_button("🔗 Ver en Dataverse", url_dataverse)
                    else:
                        st.caption("Sin enlace de Dataverse disponible para este dataset.")