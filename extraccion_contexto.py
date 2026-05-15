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

# === 2. FUNCIONES DE LIMPIEZA Y NORMALIZACIÓN ===

def limpiar_nombre_carpeta(nombre):
    """Limpia el título para que sea un nombre de carpeta válido."""
    prohibidos = '<>:"/\\|?*'
    for char in prohibidos:
        nombre = nombre.replace(char, "")
    return " ".join(nombre.split())[:100].strip()

def normalizar_autores(entrada):
    """
    Versión ultra-robusta para formatos académicos complejos.
    Maneja casos como: "[D'Haro, L.; Gil, M.,]" -> "['D\'Haro, L.', 'Gil, M.']"
    """
    if not entrada or str(entrada).strip() in ["[]", "", "None"]:
        return "[]"
    
    # 1. Convertir a string y quitar corchetes externos si existen
    texto = str(entrada).strip()
    if texto.startswith('['): texto = texto[1:]
    if texto.endswith(']'): texto = texto[:-1]
    
    # 2. Quitar comillas que puedan venir en el string para evitar conflictos
    texto = texto.replace('"', '').replace("'", "")
    
    # 3. Dividir. Priorizamos el punto y coma (estándar académico)
    if ';' in texto:
        partes = texto.split(';')
    else:
        # Si no hay punto y coma, dividimos por comas, pero esto es arriesgado 
        # si los nombres vienen como "Apellido, Nombre"
        partes = [texto] # Por defecto lo tratamos como un bloque si no hay ';'

    # 4. Limpiar cada autor individualmente
    autores_limpios = []
    for p in partes:
        nombre = p.strip()
        if not nombre: continue
        
        # Quitar coma final si existe (ej: "Fernández, F.,")
        if nombre.endswith(','):
            nombre = nombre[:-1].strip()
            
        autores_limpios.append(nombre)
    
    return str(autores_limpios)

# === 3. FUNCIONES DE IA (GROQ) ===

def extraer_info_paper(texto):
    """Extrae propuesta inicial de título, autores y contexto del PDF."""
    prompt = f"""
    Analiza este texto científico.
    Extrae el título, los autores y genera una descripción_contexto.
    Devuelve los autores como una cadena de texto separada por puntos y coma.
    
    Texto: {texto[:8000]}
    
    Responde estrictamente en formato JSON:
    {{
        "titulo": "...",
        "autores": "[Autor 1, Autor 2]",
        "descripcion_contexto": "..."
    }}
    """
    try:
        completion = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        res = json.loads(completion.choices[0].message.content)
        # Normalizamos los autores nada más recibirlos
        res['autores'] = normalizar_autores(res.get('autores', ""))
        return res
    except:
        return None

def analizar_dataset_con_contexto_previo(nombre_file, muestra, contexto_manual):
    """La IA usa el contexto definido por el usuario para explicar cada dataset."""
    prompt = f"""
    Contexto de la investigación: {contexto_manual}
    Archivo de datos: {nombre_file}
    Muestra de datos: {muestra}
    
    Tarea: Explica brevemente cómo se relaciona este archivo con el contexto. Máximo 2 frases.
    """
    try:
        completion = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content.strip()
    except:
        return "No se pudo generar descripción."

# === 4. INTERFAZ DE STREAMLIT ===

st.set_page_config(page_title="TFM Data Manager", layout="wide")
st.title("📂 Editor de Investigaciones Científicas")

# Inicialización de estados de sesión
if 'titulo' not in st.session_state: st.session_state.titulo = ""
if 'autores' not in st.session_state: st.session_state.autores = "[]"
if 'contexto' not in st.session_state: st.session_state.contexto = ""
if 'descripciones_datasets' not in st.session_state: st.session_state.descripciones_datasets = {}

# --- PASO 1: CONTEXTO ---
st.header("1. Definir Información de la Investigación")
col_f, col_t = st.columns([1, 2])

with col_f:
    up_paper = st.file_uploader("Opcional: Cargar Paper (PDF)", type="pdf")
    if up_paper and st.button("📄 Sugerir Metadatos desde PDF"):
        with st.spinner("Analizando PDF..."):
            doc = fitz.open(stream=up_paper.read(), filetype="pdf")
            texto_p = "".join([p.get_text() for p in doc[:5]])
            sug = extraer_info_paper(texto_p)
            if sug:
                st.session_state.titulo = sug['titulo']
                st.session_state.autores = sug['autores']
                st.session_state.contexto = sug['descripcion_contexto']

with col_t:
    st.session_state.titulo = st.text_input("Título oficial:", value=st.session_state.titulo)
    st.session_state.autores = st.text_input("Autores (Formato: Apellido, N; Apellido, N):", value=st.session_state.autores)
    st.session_state.contexto = st.text_area("Contexto de la investigación (guía para la IA):", 
                                            value=st.session_state.contexto, height=150)

# --- PASO 2: DATASETS ---
st.divider()
st.header("2. Cargar y Analizar Datasets")
up_datasets = st.file_uploader("Sube tus archivos de datos", accept_multiple_files=True)

if up_datasets:
    if st.button("🤖 Generar Descripciones Automáticas para Datasets"):
        if not st.session_state.contexto:
            st.warning("⚠️ Escribe primero el contexto arriba para que la IA pueda trabajar.")
        else:
            with st.spinner("Analizando datasets..."):
                for ds in up_datasets:
                    try:
                        if ds.name.endswith('.csv'):
                            preview = pd.read_csv(ds, nrows=3).to_string()
                        else:
                            preview = "Archivo de datos (Excel/Binario)"
                        ds.seek(0)
                        res_ds = analizar_dataset_con_contexto_previo(ds.name, preview, st.session_state.contexto)
                        st.session_state.descripciones_datasets[ds.name] = res_ds
                    except:
                        st.session_state.descripciones_datasets[ds.name] = "Error leyendo el archivo."

# --- PASO 3: REVISIÓN Y GUARDADO ---
if st.session_state.descripciones_datasets:
    st.subheader("📝 Revisión final de descripciones")
    desc_editadas = {}
    
    for ds in up_datasets:
        desc_editadas[ds.name] = st.text_area(
            f"Descripción de {ds.name}:", 
            value=st.session_state.descripciones_datasets.get(ds.name, ""),
            key=f"ui_{ds.name}"
        )

    st.divider()
    nombre_folder = st.text_input("Nombre de la carpeta de destino:", value=limpiar_nombre_carpeta(st.session_state.titulo))
    
    if st.button("💾 Guardar Investigación"):
        # Normalización final de seguridad
        autores_finales = normalizar_autores(st.session_state.autores)
        
        ruta_final = Path("investigaciones") / nombre_folder
        ruta_final.mkdir(parents=True, exist_ok=True)
        
        datasets_para_json = []
        for ds in up_datasets:
            with open(ruta_final / ds.name, "wb") as f:
                f.write(ds.getbuffer())
            datasets_para_json.append({
                "archivo": ds.name,
                "descripcion": desc_editadas[ds.name]
            })
        
        if up_paper:
            up_paper.seek(0)
            with open(ruta_final / "paper.pdf", "wb") as f:
                f.write(up_paper.getbuffer())
        
        metadatos = {
            "titulo": st.session_state.titulo,
            "autores": autores_finales,
            "contexto_general": st.session_state.contexto,
            "datasets": datasets_para_json
        }
        
        with open(ruta_final / "metadatos.json", "w", encoding="utf-8") as f:
            json.dump(metadatos, f, indent=4, ensure_ascii=False)
            
        st.success(f"✅ Guardado correctamente.")
        st.json(metadatos)