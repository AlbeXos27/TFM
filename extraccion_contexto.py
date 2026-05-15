import os
import json
import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
from pathlib import Path
from groq import Groq

# === 1. CONFIGURACIÓN ===
API_KEY_GROQ = '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'
MODELO_LLM = "llama-3.3-70b-versatile"
client = Groq(api_key=API_KEY_GROQ)

if not os.path.exists('investigaciones'):
    os.makedirs('investigaciones')

def limpiar_nombre_carpeta(nombre):
    prohibidos = '<>:"/\\|?*'
    for char in prohibidos:
        nombre = nombre.replace(char, "")
    return " ".join(nombre.split())[:100].strip()

def extraer_info_paper(texto):
    """Extrae una propuesta inicial de título y contexto del PDF."""
    prompt = f"Analiza este texto científico y devuelve un JSON con: titulo, autores, descripcion_contexto. Texto: {texto[:8000]}"
    try:
        completion = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except:
        return None

def analizar_dataset_con_contexto_previo(nombre_file, muestra, contexto_manual):
    prompt = f"""
    Contexto de la investigación (definido por el usuario): {contexto_manual}
    
    Archivo de datos: {nombre_file}
    Muestra de datos: {muestra}
    
    Tarea: Explica brevemente cómo se relaciona este archivo con el contexto de arriba. 
    Responde en máximo 2 frases.
    """
    try:
        completion = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content.strip()
    except:
        return "No se pudo generar descripción."

# === 2. INTERFAZ ===
st.set_page_config(page_title="TFM - Contexto Primero", layout="wide")
st.title("📂 Editor de Datos: Primero Contexto, luego IA")

# Estados de sesión
if 'titulo' not in st.session_state: st.session_state.titulo = ""
if 'autores' not in st.session_state: st.session_state.autores = ""
if 'contexto' not in st.session_state: st.session_state.contexto = ""
if 'descripciones_datasets' not in st.session_state: st.session_state.descripciones_datasets = {}

# --- PASO 1: CARGA Y DEFINICIÓN DE CONTEXTO ---
st.header("1. Definir el Contexto de la Investigación")
col_files, col_ctx = st.columns([1, 2])

with col_files:
    up_paper = st.file_uploader("Opcional: Cargar Paper para sugerencias", type="pdf")
    if up_paper and st.button("📄 Sugerir desde Paper"):
        doc = fitz.open(stream=up_paper.read(), filetype="pdf")
        texto = "".join([p.get_text() for p in doc[:5]])
        sugerencia = extraer_info_paper(texto)
        if sugerencia:
            st.session_state.titulo = sugerencia['titulo']
            st.session_state.autores = sugerencia['autores']
            st.session_state.contexto = sugerencia['descripcion_contexto']

with col_ctx:
    st.session_state.titulo = st.text_input("Título de la Investigación:", value=st.session_state.titulo)
    st.session_state.autores = st.text_input("Autores:", value=st.session_state.autores)
    st.session_state.contexto = st.text_area("ESCRIBE O EDITA EL CONTEXTO AQUÍ (La IA usará esto):", 
                                            value=st.session_state.contexto, height=150)

# --- PASO 2: ANÁLISIS DE DATASETS ---
st.divider()
st.header("2. Analizar Datasets con el contexto anterior")
up_datasets = st.file_uploader("Sube tus archivos de datos", accept_multiple_files=True)

if up_datasets:
    if st.button("🤖 Generar descripciones de datasets usando mi contexto"):
        if not st.session_state.contexto:
            st.warning("⚠️ Por favor, escribe algo en el contexto primero para que la IA sepa qué buscar.")
        else:
            with st.spinner("Analizando datasets basados en tu contexto..."):
                for ds in up_datasets:
                    # Leer muestra
                    try:
                        if ds.name.endswith('.csv'):
                            preview = pd.read_csv(ds, nrows=3).to_string()
                        else:
                            preview = "Archivo de datos Excel/Binario"
                        ds.seek(0)
                        
                        # IA analiza usando el contexto de la caja de texto
                        res = analizar_dataset_con_contexto_previo(ds.name, preview, st.session_state.contexto)
                        st.session_state.descripciones_datasets[ds.name] = res
                    except:
                        st.session_state.descripciones_datasets[ds.name] = "Error leyendo muestra."

# --- PASO 3: REVISIÓN FINAL Y GUARDADO ---
if st.session_state.descripciones_datasets:
    st.subheader("📝 Revisar descripciones generadas")
    final_desc_datasets = {}
    
    for ds in up_datasets:
        final_desc_datasets[ds.name] = st.text_area(
            f"Descripción de {ds.name}:", 
            value=st.session_state.descripciones_datasets.get(ds.name, ""),
            key=f"final_{ds.name}"
        )

    st.divider()
    nombre_folder = st.text_input("Carpeta final:", value=limpiar_nombre_carpeta(st.session_state.titulo))
    
    if st.button("💾 Guardar Todo"):
        ruta = Path("investigaciones") / nombre_folder
        ruta.mkdir(parents=True, exist_ok=True)
        
        datasets_info = []
        for ds in up_datasets:
            with open(ruta / ds.name, "wb") as f:
                f.write(ds.getbuffer())
            datasets_info.append({"archivo": ds.name, "descripcion": final_desc_datasets[ds.name]})
        
        if up_paper:
            up_paper.seek(0)
            with open(ruta / "paper.pdf", "wb") as f:
                f.write(up_paper.getbuffer())
        
        meta = {
            "titulo": st.session_state.titulo,
            "autores": st.session_state.autores,
            "contexto_general": st.session_state.contexto,
            "datasets": datasets_info
        }
        
        with open(ruta / "metadatos.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4, ensure_ascii=False)
            
        st.success("✅ Guardado con éxito.")