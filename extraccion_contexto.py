import os
import json
import requests
import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
from pathlib import Path
from groq import Groq
import re
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


def consultar_orcid(entrada_usuario):
    """
    Busca un autor en la API pública de ORCID.
    Detecta automáticamente si la entrada es un ORCID iD (código) o un nombre/apellido.
    """
    url = "https://pub.orcid.org/v3.0/expanded-search/"
    headers = {"Accept": "application/json"}
    
    # Expresión regular para detectar un formato ORCID iD (ej: 0000-0002-1825-0097)
    # Soporta que termine en 'X' o 'x' (común en algunos códigos ORCID)
    es_orcid_id = re.match(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX_x]$", entrada_usuario.strip())
    
    if es_orcid_id:
        # Si es un código, buscamos directamente por el campo exacto de orcid
        query = f"orcid:{entrada_usuario.strip()}"
    else:
        # Si es texto, mantenemos la búsqueda por tokens en nombres y apellidos
        query = " AND ".join([f"given-and-family-names:{token}~4" for token in entrada_usuario.split()])
    
    params = {
        "q": query,
        "rows": 20
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            resultados = []
            for doc in data.get("expanded-result", []):
                resultados.append({
                    "orcid": doc.get("orcid-id"),
                    "nombre_completo": f"{doc.get('given-names', '')} {doc.get('family-names', '')}".strip(),
                    "institucion": doc.get("institution-name", ["No disponible"])
                })
            return resultados
    except Exception as e:
        print(f"Error al consultar ORCID para {entrada_usuario}: {e}")
    return []

# === 3. FUNCIONES DE IA (GROQ) ===

def extraer_info_paper(texto):
    """Extrae propuesta inicial de título, autores y contexto del PDF."""
    prompt = f"""
    Analiza este texto científico.
    Extrae el título en su idioma original, los autores y genera una descripción_contexto.
    
    Texto: {texto[:8000]}
    
    Responde estrictamente en formato JSON válido.
    MUY IMPORTANTE: "autores" DEBE ser una lista de strings (un array JSON nativo).
    
    Ejemplo de formato:
    {{
        "titulo": "Título de la investigación",
        "autores": ["Nombre1 Apellido1", "Nombre2 Apellido2"],
        "descripcion_contexto": "Línea 1...\\nLínea 2...\\nLínea 3...\\nLínea 4..."
    }}
    """
    try:
        completion = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        res = json.loads(completion.choices[0].message.content)
        return res
    except:
        return None


def analizar_dataset_con_contexto_previo(nombre_file, muestra, contexto_manual):
    """La IA usa el contexto definido por el usuario para explicar cada dataset."""
    prompt = f"""
    Contexto de la investigación: {contexto_manual}
    Archivo de datos: {nombre_file}
    Muestra de datos: {muestra}
    
    Tarea: Explica brevemente qué función tiene con respecto al contexto y su utilidad.
    MÁXIMO 3 LÍNEAS
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

# Inicialización de estados de sesión corregidos
if 'titulo' not in st.session_state: st.session_state.titulo = ""
if 'autores' not in st.session_state: st.session_state.autores = []
if 'contexto' not in st.session_state: st.session_state.contexto = ""
if 'descripciones_datasets' not in st.session_state: st.session_state.descripciones_datasets = {}
if 'autores_orcid_automaticos' not in st.session_state: st.session_state.autores_orcid_automaticos = {}
if 'orcid_confirmados_manual' not in st.session_state: st.session_state.orcid_confirmados_manual = {}

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
                
                # Pre-buscamos en ORCID los autores sugeridos por el PDF
                st.session_state.autores_orcid_automaticos = {}
                for autor in sug['autores']:
                    st.session_state.autores_orcid_automaticos[autor] = consultar_orcid(autor)

with col_t:
    st.session_state.titulo = st.text_input("Título oficial:", value=st.session_state.titulo)
    
    # Visualización y edición rápida de la lista actual de autores
    autores_editables_str = st.text_input("Autores actuales (separados por comas):", value=", ".join(st.session_state.autores))
    st.session_state.autores = [a.strip() for a in autores_editables_str.split(",") if a.strip()]
    
    st.session_state.contexto = st.text_area("Contexto de la investigación (guía para la IA):", 
                                            value=st.session_state.contexto, height=150)

# --- VERIFICACIÓN DE AUTORES EXTRAÍDOS DEL PDF ---
if st.session_state.autores_orcid_automaticos:
    with st.expander("🔗 Vincular ORCID desde Autores Detectados en el PDF", expanded=True):
        orcid_seleccionados_pdf = {}
        for autor, coincidencias in st.session_state.autores_orcid_automaticos.items():
            if coincidencias:
                opciones = ["No vincular / Ninguno coincide"] + [
                    f"{c['nombre_completo']} ({c['orcid']}) - {', '.join(c['institucion'])}" 
                    for c in coincidencias
                ]
                seleccion = st.selectbox(f"Coincidencias encontradas para '{autor}':", opciones, key=f"pdf_orcid_{autor}")
                if seleccion != "No vincular / Ninguno coincide":
                    idx = opciones.index(seleccion) - 1
                    orcid_seleccionados_pdf[autor] = coincidencias[idx]
            else:
                st.caption(f"⚠️ No se encontraron registros en ORCID para el autor: *{autor}*")

# --- BUSCADOR MANUAL DE AUTORES EN ORCID (FRAGMENTADO) ---
st.write("")
with st.expander("🔍 Buscador e Incorporador Manual de Autores vía ORCID"):
    @st.fragment()
    def buscador_manual_autores():
        nombre_buscar = st.text_input("Escribe el nombre del autor a buscar:", key="input_busqueda_manual")
        if nombre_buscar:
            with st.spinner("Buscando en ORCID..."):
                coincidencias = consultar_orcid(nombre_buscar)
            
            if coincidencias:
                opciones = ["Selecciona un perfil para añadir..."] + [
                    f"{c['nombre_completo']} ({c['orcid']}) - {', '.join(c['institucion'])}" 
                    for c in coincidencias
                ]
                seleccion = st.selectbox("Perfiles devueltos:", opciones, key="select_autor_manual")
                
                if seleccion != "Selecciona un perfil para añadir...":
                    idx = opciones.index(seleccion) - 1
                    autor_sel = coincidencias[idx]
                    
                    if st.button("➕ Vincular e Insertar a la Investigación"):
                        if autor_sel["nombre_completo"] not in st.session_state.autores:
                            st.session_state.autores.append(autor_sel["nombre_completo"])
                            # Almacenamos su estructura de datos confirmada
                            st.session_state.orcid_confirmados_manual[autor_sel["nombre_completo"]] = autor_sel
                            st.success(f"Añadido: {autor_sel['nombre_completo']}")
                            st.rerun()
                        else:
                            st.warning("El autor ya se encuentra en la lista.")
            else:
                st.info("Sin resultados exactos. Puedes escribirlo directamente en el campo de texto de arriba.")

    buscador_manual_autores()


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
        
        # Consolidación estructurada de metadatos de autores
        autores_consolidados = []
        for autor in st.session_state.autores:
            if autor in st.session_state.orcid_confirmados_manual:
                info = st.session_state.orcid_confirmados_manual[autor]
                autores_consolidados.append({
                    "nombre": autor,
                    "orcid": info["orcid"],
                    "institucion": info["institucion"]
                })
            elif 'orcid_seleccionados_pdf' in locals() and autor in orcid_seleccionados_pdf:
                info = orcid_seleccionados_pdf[autor]
                autores_consolidados.append({
                    "nombre": info["nombre_completo"],
                    "orcid": info["orcid"],
                    "institucion": info["institucion"]
                })
            else:
                autores_consolidados.append({
                    "nombre": autor,
                    "orcid": None,
                    "institucion": None
                })

        metadatos = {
            "titulo": st.session_state.titulo,
            "autores": autores_consolidados,
            "contexto_general": st.session_state.contexto,
            "datasets": datasets_para_json
        }
        
        with open(ruta_final / "metadatos.json", "w", encoding="utf-8") as f:
            json.dump(metadatos, f, indent=4, ensure_ascii=False)
            
        st.success(f"✅ Guardado correctamente.")
        st.json(metadatos)