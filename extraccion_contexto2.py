import streamlit as st
import pandas as pd
import pypdf
from groq import Groq
import json
from pathlib import Path
import shutil
import requests
import re

# 🔑 Configuración de Credenciales y Modelos
API_KEY_GROQ = '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'
MODELO_LLM = "meta-llama/llama-4-scout-17b-16e-instruct"
client = Groq(api_key=API_KEY_GROQ)


def analizar_dataset_con_contexto(dataset_nombre, df, contexto):
    columnas_y_tipos = df.dtypes.to_string()
    muestra_datos = df.head(5).to_string()
    prompt_sistema = (
        "Eres un experto científico de datos. Tu tarea es explicar la utilidad de un dataset "
        "dentro de un contexto proporcionado por el usuario. Asegúrate de respetar y corregir las tildes "
        "y eñes en los textos si detectas fallos de codificación."
    )
    prompt_usuario = f"""
    Contexto general: {contexto}

    Dataset: {dataset_nombre}
    Columnas y tipos:
    {columnas_y_tipos}

    Muestra de datos:
    {muestra_datos}

    Responde en español con:
    1. Propósito general del dataset en este contexto.
    2. Qué columnas respaldan ese propósito.
    3. Recomendación breve sobre su utilidad.
    """
    try:
        respuesta = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            temperature=0.2
        )
        return respuesta.choices[0].message.content.strip()
    except Exception as e:
        return f"Error al generar descripción: {e}"


# 📡 Función de Conexión a la API Pública de ORCID v3.0
def buscar_en_orcid_real(nombre_autor):
    url = f"https://pub.orcid.org/v3.0/expanded-search/?q=text:{nombre_autor}"
    headers = {"Accept": "application/json"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            data = response.json()
            listado_resultados = ["Selecciona un resultado del listado..."]
            
            if isinstance(data, dict):
                for item in data.get("expanded-result", []):
                    if isinstance(item, dict):
                        orcid_id = item.get("orcid-id")
                        given_names = item.get("given-names", "")
                        family_names = item.get("family-names", "")
                        
                        inst_list = []
                        if isinstance(item.get("institution-name"), list):
                            inst_list = [inst.get("institution-name", "") for inst in item.get("institution-name", []) if isinstance(inst, dict) and inst.get("institution-name")]
                        
                        inst_str = f" ({', '.join(inst_list)})" if any(inst_list) else ""
                        listado_resultados.append(f"{orcid_id} - {given_names} {family_names}{inst_str}")
                
            if len(listado_resultados) == 1:
                return ["No se encontraron coincidencias en el registro de ORCID."]
            return listado_resultados
        else:
            return [f"Aviso: Servidor ORCID no disponible (Status {response.status_code})"]
    except Exception as e:
        return [f"Aviso: Sin conexión con ORCID ({str(e)})"]


# 🛠️ Configuración global de la interfaz
st.set_page_config(layout="wide")

st.title("Extracción de Contexto y Enlace Académico")

# Inicialización segura de st.session_state
if 'analisis_datasets' not in st.session_state:
    st.session_state.analisis_datasets = {}
if 'contextos_datasets' not in st.session_state:
    st.session_state.contextos_datasets = {}
if 'metadatos_articulos_editados' not in st.session_state:
    st.session_state.metadatos_articulos_editados = {}
if 'metadatos_datasets_editados' not in st.session_state:
    st.session_state.metadatos_datasets_editados = {}
if 'textos_articulos' not in st.session_state:
    st.session_state.textos_articulos = {}

# =====================================================================
# --- SECCIÓN 1: DATASETS ---
# =====================================================================
st.header("1. Datasets")

archivos_a = st.file_uploader("Sube uno o varios datasets", type=["csv", "xlsx"], key="uploader_a", accept_multiple_files=True)

datasets_dict = {}

if archivos_a:
    st.success(f"¡{len(archivos_a)} dataset(s) cargado(s) con éxito!")
    for archivo in archivos_a:
        if archivo.name.endswith(('.xlsx', '.xls')):
            datasets_dict[archivo.name] = pd.read_excel(archivo)
        else:
            try:
                datasets_dict[archivo.name] = pd.read_csv(archivo, encoding='utf-8')
            except UnicodeDecodeError:
                try:
                    datasets_dict[archivo.name] = pd.read_csv(archivo, encoding='latin-1')
                except Exception as e:
                    st.error(f"No se pudo leer el archivo {archivo.name}: {e}")

    for dataset_name, df in datasets_dict.items():
        if dataset_name not in st.session_state.analisis_datasets:
            with st.spinner(f"Analizando estructura y autores de {dataset_name}..."):
                columnas_y_tipos = df.dtypes.to_string()
                muestra_datos = df.head(5).to_string()
                
                prompt_sistema = (
                    "Eres un experto científico de datos e investigador. Tu objetivo es explicar la estructura, "
                    "el propósito de un dataset y deducir/extraer posibles autores, investigadores o entidades creadoras basándote en sus metadatos o contenido. "
                    "Asegúrate de escribir correctamente los nombres propios con sus tildes y eñes correspondientes en español."
                )
                
                # 🌟 MEJORA PROMPT: Regla estricta para evitar textos alternativos si no hay autores
                prompt_usuario = f"""
                Analiza el archivo '{dataset_name}'.
                Columnas y tipos de datos:
                {columnas_y_tipos}
                Muestra de las primeras 5 filas:
                {muestra_datos}
                
                Genera una respuesta UNICAMENTE en formato JSON válido con la siguiente estructura.
                CRÍTICO: Si no hay autores, creadores o instituciones claras, deja la lista de "autores_detectados" completamente vacía: []. No escribas textos explicativos dentro de la lista.
                
                {{
                    "proposito_general": "Breve explicación de para qué sirve este archivo.",
                    "explicacion_campos": "Desglose rápido de las variables clave.",
                    "autores_detectados": []
                }}
                """
                try:
                    respuesta = client.chat.completions.create(
                        model=MODELO_LLM,
                        messages=[
                            {"role": "system", "content": prompt_sistema},
                            {"role": "user", "content": prompt_usuario}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.2
                    )
                    
                    res_json = json.loads(respuesta.choices[0].message.content)
                    
                    texto_analisis = f"**Propósito General:** {res_json.get('proposito_general')}\n\n**Explicación de Campos:** {res_json.get('explicacion_campos')}"
                    st.session_state.analisis_datasets[dataset_name] = texto_analisis
                    
                    # 🌟 FILTRO PYTHON: Si la IA escribe una frase larga en vez de un nombre, la borramos
                    autores_raw = res_json.get("autores_detectados", [])
                    autores_filtrados = [
                        a for a in autores_raw 
                        if len(a) < 50 and "no se puede" not in a.lower() and "inferir" not in a.lower() and "desconocido" not in a.lower()
                    ]
                    
                    st.session_state.metadatos_datasets_editados[dataset_name] = {
                        "titulo": dataset_name,
                        "autores_detectados": autores_filtrados,
                        "autores_finales_seleccionados": autores_filtrados,
                        "orcids_vinculados": {},
                        "resultados_busqueda_api": {}
                    }
                    
                except Exception as e:
                    st.session_state.analisis_datasets[dataset_name] = f"Error al analizar: {e}"
                    st.session_state.metadatos_datasets_editados[dataset_name] = {
                        "titulo": dataset_name,
                        "autores_detectados": [],
                        "autores_finales_seleccionados": [],
                        "orcids_vinculados": {},
                        "resultados_busqueda_api": {}
                    }
    
    if st.session_state.analisis_datasets:
        st.markdown("---")
        st.subheader("📋 Ver y Gestionar Datasets")
        dataset_seleccionado = st.selectbox(
            "Selecciona un dataset para ver su análisis y autores:",
            options=list(st.session_state.analisis_datasets.keys()),
            key="select_dataset_analisis"
        )
        
        if dataset_seleccionado:
            st.info("💡 **Análisis de Groq:**")
            st.markdown(st.session_state.analisis_datasets[dataset_seleccionado])
            
            st.markdown("---")
            st.subheader(f"✍️ Contexto Específico para: {dataset_seleccionado}")
            contexto_dataset = st.text_area(
                f"Escribe el contexto específico para {dataset_seleccionado}:",
                value=st.session_state.contextos_datasets.get(dataset_seleccionado, ""),
                height=120,
                key=f"ctx_{dataset_seleccionado}"
            )
            if contexto_dataset:
                st.session_state.contextos_datasets[dataset_seleccionado] = contexto_dataset
                st.success("✅ Contexto guardado para este dataset")
                
            # 👥 CONTROL DE AUTORES DEL DATASET
            st.markdown("#### 👥 Autores / Creadores del Dataset")
            datos_ds_actuales = st.session_state.metadatos_datasets_editados[dataset_seleccionado]
            
            with st.form(key=f"form_autor_manual_ds_{dataset_seleccionado}", clear_on_submit=True):
                col_input_ds, col_btn_ds = st.columns([4, 1])
                with col_input_ds:
                    nuevo_autor_ds = st.text_input(
                        "➕ ¿Falta algún creador/autor en este Dataset? Escribe su nombre completo:", 
                        placeholder="Ej. Juan Pérez"
                    )
                with col_btn_ds:
                    st.markdown("<div style='padding-top: 24px;'></div>", unsafe_allow_html=True)
                    btn_agregar_ds = st.form_submit_button("Añadir autor al Dataset", use_container_width=True)

                if btn_agregar_ds and nuevo_autor_ds.strip():
                    nombre_limpio_ds = nuevo_autor_ds.strip()
                    if nombre_limpio_ds not in datos_ds_actuales["autores_finales_seleccionados"]:
                        datos_ds_actuales["autores_finales_seleccionados"].append(nombre_limpio_ds)
                    st.rerun()
            
            autores_ds_actuales = datos_ds_actuales["autores_finales_seleccionados"]
            
            if autores_ds_actuales:
                cols_etiquetas_ds = st.columns(len(autores_ds_actuales) if len(autores_ds_actuales) > 0 else 1)
                autor_ds_a_eliminar = None
                for idx_a, autor_ds in enumerate(autores_ds_actuales):
                    with cols_etiquetas_ds[idx_a]:
                        id_orcid_ds = datos_ds_actuales.get("orcids_vinculados", {}).get(autor_ds, "")
                        label_ds = f"📊 {autor_ds} ({id_orcid_ds})  ❌" if id_orcid_ds else f"📊 {autor_ds}  ❌"
                        if st.button(label_ds, key=f"del_ds_{dataset_seleccionado}_{autor_ds}_{idx_a}", use_container_width=True):
                            autor_ds_a_eliminar = autor_ds
                
                if autor_ds_a_eliminar:
                    datos_ds_actuales["autores_finales_seleccionados"].remove(autor_ds_a_eliminar)
                    if autor_ds_a_eliminar in datos_ds_actuales.get("orcids_vinculados", {}):
                        del datos_ds_actuales["orcids_vinculados"][autor_ds_a_eliminar]
                    st.rerun()

                # Gestión ORCID para Datasets
                st.markdown("##### 🔍 Identificador ORCID para Creadores de Datasets")
                for autor_ds in autores_ds_actuales:
                    if autor_ds not in datos_ds_actuales.get("resultados_busqueda_api", {}):
                        with st.spinner(f"Buscando '{autor_ds}' en ORCID..."):
                            datos_ds_actuales.setdefault("resultados_busqueda_api", {})[autor_ds] = buscar_en_orcid_real(autor_ds)
                    
                    with st.expander(f"Gestionar ORCID para creador: {autor_ds}", expanded=False):
                        sb_key_ds = f"select_orcid_ds_{dataset_seleccionado}_{autor_ds}"
                        
                        def actualizar_orcid_ds(ds_key, aut_key, sb_k):
                            sel = st.session_state[sb_k]
                            if sel and "0000-" in sel:
                                cod = sel.split(" - ")[0].strip()
                                st.session_state.metadatos_datasets_editados[ds_key]["orcids_vinculados"][aut_key] = cod
                                st.session_state[f"final_orcid_ds_{ds_key}_{aut_key}"] = cod

                        st.selectbox(
                            "Coincidencias encontradas:",
                            options=datos_ds_actuales["resultados_busqueda_api"].get(autor_ds, ["Selecciona..."]),
                            key=sb_key_ds,
                            on_change=actualizar_orcid_ds,
                            args=(dataset_seleccionado, autor_ds, sb_key_ds)
                        )
                        
                        input_key_ds = f"final_orcid_ds_{dataset_seleccionado}_{autor_ds}"
                        if input_key_ds not in st.session_state:
                            st.session_state[input_key_ds] = datos_ds_actuales["orcids_vinculados"].get(autor_ds, "")
                        
                        orcid_conf = st.text_input("ORCID Creador Definitivo:", key=input_key_ds)
                        if orcid_conf != datos_ds_actuales["orcids_vinculados"].get(autor_ds, ""):
                            datos_ds_actuales["orcids_vinculados"][autor_ds] = orcid_conf
                            st.rerun()
            else:
                st.info("No se han detectado autores para este dataset. Puedes añadir uno manualmente arriba.")

st.markdown("---") 

# =====================================================================
# --- SECCIÓN 2: ARTÍCULOS Y AUTORES ---
# =====================================================================
st.header("2. Artículos")

archivos_b = st.file_uploader("Sube uno o varios artículos (PDF)", type=["pdf"], key="uploader_b", accept_multiple_files=True)

articulos_dict = {}

if archivos_b:
    st.success(f"¡{len(archivos_b)} artículo(s) PDF cargado(s) con éxito!")
    for archivo in archivos_b:
        try:
            archivo.seek(0)
            pdf_bytes = archivo.read()
            lector_pdf = pypdf.PdfReader(archivo)
            
            autores_metadatos = []
            if lector_pdf.metadata and lector_pdf.metadata.author:
                autor_raw = lector_pdf.metadata.author.strip()
                autor_limpio = re.sub(r'\b(and|y|\&)\b', ',', autor_raw, flags=re.IGNORECASE)
                
                if ";" in autor_limpio:
                    autores_metadatos = [a.strip() for a in autor_limpio.split(";") if a.strip()]
                else:
                    autores_metadatos = [a.strip() for a in autor_limpio.split(",") if a.strip()]

            texto_pdf = ""
            num_paginas_extraer = min(3, len(lector_pdf.pages))
            for i in range(num_paginas_extraer):
                try:
                    texto_pdf += f"\n--- Página {i+1} ---\n"
                    texto_pdf += lector_pdf.pages[i].extract_text()
                except:
                    texto_pdf += f"\n[No se pudo extraer texto de la página {i+1}]\n"
            
            st.session_state.textos_articulos[archivo.name] = texto_pdf
            articulos_dict[archivo.name] = pdf_bytes
            
            if archivo.name not in st.session_state.metadatos_articulos_editados:
                st.session_state.metadatos_articulos_editados[archivo.name] = {
                    "autores_pdf_metadatos": autores_metadatos,
                    "autores_detectados": [],  
                    "autores_finales_seleccionados": [],
                    "orcids_vinculados": {},
                    "resultados_busqueda_api": {}
                }
            else:
                st.session_state.metadatos_articulos_editados[archivo.name]["autores_pdf_metadatos"] = autores_metadatos
            
        except Exception as e:
            st.error(f"No se pudo leer el PDF {archivo.name}: {e}")

    articulo_visualizar = st.selectbox("Selecciona un Artículo para gestionar sus metadatos y autores:", list(articulos_dict.keys()))
    
    if articulo_visualizar:
        datos_actuales = st.session_state.metadatos_articulos_editados[articulo_visualizar]
        
        if not datos_actuales.get("autores_detectados") and "titulo" not in datos_actuales:
            if articulo_visualizar in st.session_state.textos_articulos:
                texto_pdf = st.session_state.textos_articulos[articulo_visualizar][:4000]
                
                with st.spinner(f"Extrayendo autores y contexto de {articulo_visualizar} con IA..."):
                    # 🌟 MEJORA PROMPT ARTÍCULOS: Regla estricta para evitar frases explicativas
                    prompt_metadatos = f"""
                    Analiza este fragmento de un documento académico y extrae la información.
                    Necesito el título del artículo, una lista de los nombres de los autores, y un resumen único del contexto.
                    Corrija activamente cualquier fallo de caracteres o tildes rotas que provengan de la extracción del documento.
                    
                    CRÍTICO: Si no consigues identificar autores, deja el arreglo "autores_detectados" completamente vacío: []. No metas frases descriptivas adentro.
                    
                    Responde ÚNICAMENTE con un objeto JSON estructurado con este formato exacto:
                    {{
                        "titulo": "Título completo del documento con tildes correctas",
                        "autores_detectados": [],
                        "contexto_unico": "Resumen del marco académico de este paper."
                    }}
                    
                    Texto:
                    {texto_pdf}
                    """
                    try:
                        respuesta = client.chat.completions.create(
                            model=MODELO_LLM,
                            messages=[{"role": "user", "content": prompt_metadatos}],
                            response_format={"type": "json_object"},
                            temperature=0.2
                        )
                        
                        try:
                            resultado = json.loads(respuesta.choices[0].message.content)
                            if not isinstance(resultado, dict):
                                resultado = {}
                        except:
                            resultado = {}
                        
                        datos_actuales["titulo"] = resultado.get("titulo", articulo_visualizar)
                        datos_actuales["contexto_unico"] = resultado.get("contexto_unico", "No se pudo generar el contexto automáticamente.")
                        
                        # 🌟 FILTRO PYTHON ARTÍCULOS
                        autores_art_raw = resultado.get("autores_detectados", [])
                        autores_art_filtrados = [
                            a for a in autores_art_raw 
                            if len(a) < 50 and "no se puede" not in a.lower() and "inferir" not in a.lower() and "desconocido" not in a.lower()
                        ]
                        
                        datos_actuales["autores_detectados"] = autores_art_filtrados
                        
                        lista_inicial = list(set(datos_actuales["autores_pdf_metadatos"] + datos_actuales["autores_detectados"]))
                        datos_actuales["autores_finales_seleccionados"] = [a for a in lista_inicial if a]
                        
                        st.success("✅ Autores y contexto inicializados con IA")
                    except Exception as e:
                        datos_actuales["titulo"] = articulo_visualizar
                        datos_actuales["contexto_unico"] = "No se pudo generar el contexto automáticamente."
                        datos_actuales["autores_detectados"] = []
                        datos_actuales["autores_finales_seleccionados"] = datos_actuales["autores_pdf_metadatos"].copy()
                        st.error(f"Error al procesar con IA: {e}")

        st.markdown("---")
        
        st.subheader("📄 Información General del Artículo")
        titulo_editado = st.text_input("Título del documento:", value=datos_actuales.get("titulo", ""), key=f"tit_{articulo_visualizar}")
        datos_actuales["titulo"] = titulo_editado
        
        contexto_editado = st.text_area("Contexto único de este artículo:", value=datos_actuales.get("contexto_unico", ""), height=100, key=f"ctx_{articulo_visualizar}")
        datos_actuales["contexto_unico"] = contexto_editado
        
        st.subheader("👥 Comparativa y Control de Autores")
        col_meta, col_ia = st.columns(2)
        with col_meta:
            st.markdown("**📂 Encontrados en Metadatos del PDF (Limpios):**")
            autores_pdf = datos_actuales.get("autores_pdf_metadatos", [])
            if autores_pdf:
                for a in autores_pdf:
                    st.markdown(f"- `{a}`")
            else:
                st.caption("Ninguno registrado en las propiedades del archivo.")
                
        with col_ia:
            st.markdown("**🤖 Extraídos por Inteligencia Artificial:**")
            autores_ia = datos_actuales.get("autores_detectados", [])
            if autores_ia:
                for a in autores_ia:
                    st.markdown(f"- `{a}`")
            else:
                st.caption("La IA no logró identificar nombres de autores.")

        st.markdown("#### 👥 Autores Definitivos Configurados")
        
        if "autores_finales_seleccionados" not in datos_actuales or not datos_actuales["autores_finales_seleccionados"]:
            lista_unificada = list(set(autores_pdf + autores_ia))
            datos_actuales["autores_finales_seleccionados"] = [a for a in lista_unificada if a]

        with st.form(key=f"form_autor_manual_{articulo_visualizar}", clear_on_submit=True):
            col_input, col_btn = st.columns([4, 1])
            with col_input:
                nuevo_autor_manual = st.text_input(
                    "➕ ¿Falta algún autor? Escribe su nombre completo aquí y pulsa Añadir:", 
                    placeholder="Ej. Juan Pérez"
                )
            with col_btn:
                st.markdown("<div style='padding-top: 24px;'></div>", unsafe_allow_html=True)
                btn_agregar = st.form_submit_button("Añadir autor", use_container_width=True)

            if btn_agregar and nuevo_autor_manual.strip():
                nombre_limpio = nuevo_autor_manual.strip()
                if nombre_limpio not in datos_actuales["autores_finales_seleccionados"]:
                    datos_actuales["autores_finales_seleccionados"].append(nombre_limpio)
                st.rerun()

        autores_actuales = datos_actuales["autores_finales_seleccionados"]
        
        if autores_actuales:
            st.caption("Haz clic en la ❌ de cualquier autor para removerlo del artículo:")
            cols_etiquetas = st.columns(len(autores_actuales) if len(autores_actuales) > 0 else 1)
            
            autor_a_eliminar = None
            for idx_a, autor in enumerate(autores_actuales):
                with cols_etiquetas[idx_a]:
                    id_orcid_guardado = datos_actuales.get("orcids_vinculados", {}).get(autor, "")
                    label_visual = f"👤 {autor} ({id_orcid_guardado})  ❌" if id_orcid_guardado else f"👤 {autor}  ❌"
                    
                    if st.button(label_visual, key=f"del_{articulo_visualizar}_{autor}_{idx_a}", use_container_width=True):
                        autor_a_eliminar = autor
            
            if autor_a_eliminar:
                datos_actuales["autores_finales_seleccionados"].remove(autor_a_eliminar)
                if autor_a_eliminar in datos_actuales.get("orcids_vinculados", {}):
                    del datos_actuales["orcids_vinculados"][autor_a_eliminar]
                st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)
            
            st.markdown("#### 🔍 Identificador de ORCID por Investigador (Búsqueda Automática)")
            for autor in autores_actuales:
                if autor not in datos_actuales.get("resultados_busqueda_api", {}):
                    datos_actuales.setdefault("resultados_busqueda_api", {})[autor] = buscar_en_orcid_real(autor)
                
                with st.expander(f"Gestionar ORCID para: {autor}", expanded=False):
                    nombre_a_buscar = st.text_input(
                        f"Refinar texto de búsqueda si es necesario:",
                        value=autor,
                        key=f"search_name_{articulo_visualizar}_{autor}"
                    )
                    
                    btn_buscar = st.button("🔄 Volver a buscar con el nuevo texto", key=f"btn_search_{articulo_visualizar}_{autor}")
                    
                    if btn_buscar and nombre_a_buscar:
                        with st.spinner(f"Re-buscando '{nombre_a_buscar}'..."):
                            datos_actuales["resultados_busqueda_api"][autor] = buscar_en_orcid_real(nombre_a_buscar)
                            st.rerun()
                    
                    options_actuales = datos_actuales["resultados_busqueda_api"].get(autor, ["Selecciona un resultado del listado..."])
                    
                    def actualizar_orcid_seleccionado(art_key, autor_key, sb_key):
                        seleccion = st.session_state[sb_key]
                        if seleccion and "0000-" in seleccion:
                            codigo_extraido = seleccion.split(" - ")[0].strip()
                            st.session_state.metadatos_articulos_editados[art_key]["orcids_vinculados"][autor_key] = codigo_extraido
                            st.session_state[f"final_orcid_{art_key}_{autor_key}"] = codigo_extraido

                    sb_key = f"select_orcid_list_{articulo_visualizar}_{autor}"
                    
                    st.selectbox(
                        "Coincidencias encontradas en ORCID:",
                        options=options_actuales,
                        key=sb_key,
                        on_change=actualizar_orcid_seleccionado,
                        args=(articulo_visualizar, autor, sb_key)
                    )
                    
                    valor_actual_orcid = datos_actuales["orcids_vinculados"].get(autor, "")
                    input_key = f"final_orcid_{articulo_visualizar}_{autor}"
                    
                    if input_key not in st.session_state:
                        st.session_state[input_key] = valor_actual_orcid
                    
                    orcid_confirmado = st.text_input("ORCID Definitivo:", key=input_key)
                    
                    if orcid_confirmado != valor_actual_orcid:
                        datos_actuales["orcids_vinculados"][autor] = orcid_confirmado
                        st.rerun()
        else:
            st.info("No se han detectado autores para este artículo. Puedes añadir uno manualmente arriba.")

st.markdown("---")

# =====================================================================
# --- SECCIÓN 3: GUARDAR COMBINACIONES ---
# =====================================================================
if datasets_dict or st.session_state.analisis_datasets:
    st.header("💾 3. Guardar Combinaciones Resultantes")
    
    if 'carpetas_destino' not in st.session_state:
        st.session_state.carpetas_destino = []
    
    num_carpetas = st.number_input("¿Cuántas carpetas deseas crear?", min_value=1, max_value=10, value=1, step=1)
    
    if len(st.session_state.carpetas_destino) < num_carpetas:
        st.session_state.carpetas_destino.extend([{"nombre": "", "ruta": "", "relaciones_cruzadas": {}} for _ in range(num_carpetas - len(st.session_state.carpetas_destino))])
    elif len(st.session_state.carpetas_destino) > num_carpetas:
        st.session_state.carpetas_destino = st.session_state.carpetas_destino[:num_carpetas]
    
    for idx in range(num_carpetas):
        with st.expander(f"📁 Configurar Carpeta {idx + 1}", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                nombre = st.text_input(f"Nombre carpeta {idx + 1}:", value=st.session_state.carpetas_destino[idx]["nombre"], key=f"n_carp_{idx}")
                st.session_state.carpetas_destino[idx]["nombre"] = nombre
            with col2:
                ruta = st.text_input(f"Ruta base {idx + 1} (Vacío para Escritorio):", value=st.session_state.carpetas_destino[idx]["ruta"], key=f"r_carp_{idx}")
                st.session_state.carpetas_destino[idx]["ruta"] = ruta
            
            datasets_seleccionados = st.multiselect(f"Datasets para Carpeta {idx + 1}:", options=list(datasets_dict.keys()), default=list(datasets_dict.keys()), key=f"sel_d_{idx}")
            pdfs_seleccionados = st.multiselect(f"Artículos para Carpeta {idx + 1}:", options=list(articulos_dict.keys()), default=list(articulos_dict.keys()), key=f"sel_p_{idx}")
            
            st.session_state.carpetas_destino[idx]["datasets_seleccionados"] = datasets_seleccionados
            st.session_state.carpetas_destino[idx]["pdfs_seleccionados"] = pdfs_seleccionados

            if datasets_seleccionados and pdfs_seleccionados:
                if st.button(f"🤖 Generar Relaciones Cruzadas con IA (Carpeta {idx + 1})", key=f"btn_ia_{idx}"):
                    st.session_state.carpetas_destino[idx].setdefault("relaciones_cruzadas", {})
                    
                    for p_name in pdfs_seleccionados:
                        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"].setdefault(p_name, {})
                        contexto_art = st.session_state.metadatos_articulos_editados.get(p_name, {}).get("contexto_unico", "")
                        
                        for d_name in datasets_seleccionados:
                            df = datasets_dict[d_name]
                            with st.spinner(f"Vinculando `{d_name}` con el artículo `{p_name}`..."):
                                prompt_relacion = f"""
                                Teniendo en cuenta el contexto único de este artículo académico: "{contexto_art}"
                                Y evaluando este dataset '{d_name}' con las columnas: {df.columns.tolist()}
                                Escribe una explicación clara en español (máximo 4 líneas) sobre cómo se relaciona este dataset.
                                Asegúrate de incluir tildes correctas.
                                """
                                try:
                                    res_ia = client.chat.completions.create(
                                        model=MODELO_LLM,
                                        messages=[{"role": "user", "content": prompt_relacion}],
                                        temperature=0.3
                                    )
                                    st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name][d_name] = res_ia.choices[0].message.content.strip()
                                except Exception as e:
                                    st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name][d_name] = f"Error: {e}"

            if "relaciones_cruzadas" in st.session_state.carpetas_destino[idx] and pdfs_seleccionados:
                st.markdown("### 📝 Relaciones del Dataset con el Contexto de cada Artículo:")
                for p_name in pdfs_seleccionados:
                    if p_name in st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]:
                        st.markdown(f"##### 📄 Artículo: `{p_name}`")
                        for d_name in datasets_seleccionados:
                            relacion_actual = st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name].get(d_name, "")
                            rel_editada = st.text_area(f"Relación de `{d_name}` con este paper:", value=relacion_actual, height=80, key=f"area_{idx}_{p_name}_{d_name}")
                            st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name][d_name] = rel_editada

    if st.button("💾 Guardar Estructura Completa en Carpetas Físicas", type="primary", use_container_width=True):
        for idx, config_carpeta in enumerate(st.session_state.carpetas_destino):
            nombre_carpeta = config_carpeta["nombre"] or f"proyecto_{idx + 1}"
            ruta_base = config_carpeta["ruta"]
            ruta_final = Path(ruta_base) / nombre_carpeta if ruta_base else Path.home() / "Desktop" / nombre_carpeta
            ruta_final.mkdir(parents=True, exist_ok=True)
            
            (ruta_final / "datasets").mkdir(exist_ok=True)
            (ruta_final / "articulos").mkdir(exist_ok=True)
            
            for d_name in config_carpeta.get("datasets_seleccionados", []):
                if d_name in datasets_dict:
                    df = datasets_dict[d_name]
                    df.to_csv(ruta_final / "datasets" / d_name, index=False) if d_name.endswith('.csv') else df.to_excel(ruta_final / "datasets" / d_name, index=False)
            
            for p_name in config_carpeta.get("pdfs_seleccionados", []):
                if p_name in articulos_dict:
                    with open(ruta_final / "articulos" / p_name, 'wb') as f:
                        f.write(articulos_dict[p_name])
            
            json_salida = {
                "fecha_subida": str(pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")),
                "articulos": [],
                "datasets_globales": []
            }
            
            # 1. Guardar autores y datos de los Datasets dentro de la estructura general
            for d_name in config_carpeta.get("datasets_seleccionados", []):
                meta_ds = st.session_state.metadatos_datasets_editados.get(d_name, {})
                lista_autores_ds = meta_ds.get("autores_finales_seleccionados", [])
                
                if not lista_autores_ds:
                    autores_ds_json = ""
                else:
                    autores_ds_json = [{
                        "nombre": a_nom,
                        "orcid": meta_ds.get("orcids_vinculados", {}).get(a_nom, "")
                    } for a_nom in lista_autores_ds]
                
                json_salida["datasets_globales"].append({
                    "archivo": d_name,
                    "autores": autores_ds_json,
                    "contexto_asociado": st.session_state.contextos_datasets.get(d_name, ""),
                    "analisis_estructural": st.session_state.analisis_datasets.get(d_name, "")
                })
            
            # 2. Guardar artículos con sus autores y relaciones
            for p_name in config_carpeta.get("pdfs_seleccionados", []):
                meta_art = st.session_state.metadatos_articulos_editados.get(p_name, {})
                lista_autores_art = meta_art.get("autores_finales_seleccionados", [])
                
                if not lista_autores_art:
                    autores_art_json = ""
                else:
                    autores_art_json = [{
                        "nombre": autor_nom,
                        "orcid": meta_art.get("orcids_vinculados", {}).get(autor_nom, "")
                    } for autor_nom in lista_autores_art]
                
                estructura_articulo = {
                    "titulo": meta_art.get("titulo", p_name),
                    "autores": autores_art_json,
                    "contexto_unico": meta_art.get("contexto_unico", ""),
                    "relaciones_datasets": []
                }
                
                for d_name in config_carpeta.get("datasets_seleccionados", []):
                    relacion_explicacion = config_carpeta.get("relaciones_cruzadas", {}).get(p_name, {}).get(d_name, "Sin relación generada.")
                    estructura_articulo["relaciones_datasets"].append({
                        "archivo_dataset": d_name,
                        "relacion_con_contexto": relacion_explicacion
                    })
                
                json_salida["articulos"].append(estructura_articulo)
            
            # Guardado definitivo con tildes forzadas en UTF-8
            json_string = json.dumps(json_salida, indent=4, ensure_ascii=False)
            (ruta_final / "metadatos.json").write_text(json_string, encoding='utf-8')
                
        st.success("🎉 ¡Estructura y metadatos JSON unificados guardados con éxito en disco!")
        st.balloons()