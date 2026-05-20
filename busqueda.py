import os
import chromadb
import torch
import streamlit as st

from sentence_transformers import SentenceTransformer
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification
)

# =========================================================
# CONFIG STREAMLIT
# =========================================================

st.set_page_config(
    page_title="Buscador Científico IA",
    page_icon="🔬",
    layout="wide"
)

# =========================================================
# OPTIMIZACIONES CUDA
# =========================================================

os.environ["TOKENIZERS_PARALLELISM"] = "false"

torch.backends.cuda.matmul.allow_tf32 = True
torch.set_float32_matmul_precision("high")

device = "cuda" if torch.cuda.is_available() else "cpu"

# =========================================================
# CARGA PERSISTENTE DE MODELOS
# =========================================================

@st.cache_resource
def cargar_embedding_model():

    model = SentenceTransformer(
        "BAAI/bge-m3",
        device=device,
        model_kwargs=(
            {"torch_dtype": torch.float16}
            if device == "cuda"
            else {}
        )
    )

    return model


@st.cache_resource
def cargar_reranker():

    modelo_reranker_name = "BAAI/bge-reranker-v2-m3"

    tokenizer = AutoTokenizer.from_pretrained(
        modelo_reranker_name
    )

    model = AutoModelForSequenceClassification.from_pretrained(
        modelo_reranker_name
    )

    model.to(device)

    if device == "cuda":
        model.half()

    model.eval()

    return tokenizer, model


@st.cache_resource
def cargar_chroma():

    chroma_client = chromadb.PersistentClient(
        path="chroma_db"
    )

    collection = chroma_client.get_or_create_collection(
        name="datasets_metadata_v3_bge",
        metadata={"hnsw:space": "cosine"}
    )

    return collection


# =========================================================
# INICIALIZACIÓN
# =========================================================

with st.spinner("⏳ Cargando modelos IA..."):

    embedding_model = cargar_embedding_model()

    tokenizer_rerank, model_rerank = cargar_reranker()

    collection = cargar_chroma()

# =========================================================
# FUNCIONES
# =========================================================

def generar_embedding(texto):

    embedding = embedding_model.encode(
        texto,
        normalize_embeddings=True,
        batch_size=32,
        convert_to_numpy=True,
        show_progress_bar=False
    )

    return embedding.tolist()


def calcular_scores_reranker(query, documentos):

    pares = [[query, doc] for doc in documentos]

    inputs = tokenizer_rerank(
        pares,
        padding=True,
        truncation=True,
        max_length=1024,
        return_tensors="pt"
    )

    inputs = {
        k: v.to(device)
        for k, v in inputs.items()
    }

    with torch.no_grad():

        outputs = model_rerank(**inputs)

        scores = (
            outputs
            .logits
            .view(-1)
            .float()
            .cpu()
            .tolist()
        )

    return scores


def buscar(query_usuario, top_k=10):

    query_embedding = generar_embedding(
        query_usuario.lower()
    )

    resultado_chroma = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )

    ids_candidatos = (
        resultado_chroma["ids"][0]
        if resultado_chroma["ids"]
        else []
    )

    documentos_candidatos = (
        resultado_chroma["documents"][0]
        if resultado_chroma["documents"]
        else []
    )

    metadatas_candidatos = (
        resultado_chroma["metadatas"][0]
        if resultado_chroma["metadatas"]
        else []
    )

    distancias_chroma = (
        resultado_chroma["distances"][0]
        if resultado_chroma["distances"]
        else []
    )

    if not documentos_candidatos:
        return []

    puntuaciones_reranker = calcular_scores_reranker(
        query_usuario.lower(),
        documentos_candidatos
    )

    resultados = list(zip(
        ids_candidatos,
        documentos_candidatos,
        metadatas_candidatos,
        distancias_chroma,
        puntuaciones_reranker
    ))

    resultados = sorted(
        resultados,
        key=lambda x: x[4],
        reverse=True
    )

    return resultados


# =========================================================
# UI
# =========================================================

st.title("🔬 Buscador Científico Semántico")
st.caption("BGE-M3 + ChromaDB + BGE-Reranker-v2-m3")

# =========================================================
# INFO GPU
# =========================================================

with st.sidebar:

    st.header("⚙️ Sistema")

    st.write(f"**Device:** {device.upper()}")

    if device == "cuda":
        st.success(torch.cuda.get_device_name(0))

        memoria_total = (
            torch.cuda.get_device_properties(0).total_memory
            / 1024**3
        )

        st.write(f"VRAM: {memoria_total:.1f} GB")

    top_k = st.slider(
        "Top K candidatos",
        min_value=3,
        max_value=30,
        value=10
    )

# =========================================================
# INPUT
# =========================================================

query = st.text_input(
    "💬 Introduce tu consulta científica",
    placeholder="Ejemplo: datasets sobre enfermedades cardiovasculares..."
)

# =========================================================
# BÚSQUEDA
# =========================================================

if st.button("🔍 Buscar"):

    if not query.strip():

        st.warning("Introduce una consulta")

    else:

        with st.spinner("🧠 Analizando documentos..."):

            resultados = buscar(
                query,
                top_k=top_k
            )

        if not resultados:

            st.error("No se encontraron resultados")

        else:

            st.success(
                f"✅ {len(resultados)} resultados encontrados"
            )

            # =================================================
            # RESULTADOS
            # =================================================

            for i, resultado in enumerate(resultados, start=1):

                (
                    id_doc,
                    documento,
                    metadata,
                    distancia,
                    score
                ) = resultado

                with st.expander(
                    f"#{i} — {metadata.get('archivo', 'Dataset')}"
                ):

                    col1, col2 = st.columns(2)

                    with col1:
                        st.metric(
                            "🔥 Score Reranker",
                            f"{score:.4f}"
                        )

                    with col2:
                        st.metric(
                            "📐 Distancia Chroma",
                            f"{distancia:.4f}"
                        )

                    st.markdown("### 📌 ID")
                    st.code(id_doc)

                    st.markdown("### 📂 Investigación")
                    st.write(
                        metadata.get(
                            "investigacion",
                            "Sin información"
                        )
                    )

                    st.markdown("### 👥 Autores")
                    st.write(
                        metadata.get(
                            "autores",
                            "No especificados"
                        )
                    )

                    st.markdown("### 📄 Documento indexado")

                    st.write(documento)

# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "⚡ Arquitectura: BGE-M3 → ChromaDB → BGE-Reranker-v2-m3"
)