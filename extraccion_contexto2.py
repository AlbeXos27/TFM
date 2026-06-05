import streamlit as st
import pandas as pd
import pypdf
from groq import Groq
import json
from pathlib import Path
import shutil

API_KEY_GROQ = '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'
MODELO_LLM = "meta-llama/llama-4-scout-17b-16e-instruct"
client = Groq(api_key=API_KEY_GROQ)


def analizar_dataset_con_contexto(dataset_nombre, df, contexto):
    columnas_y_tipos = df.dtypes.to_string()
    muestra_datos = df.head(5).to_string()
    prompt_sistema = (
        "Eres un experto científico de datos. Tu tarea es explicar la utilidad de un dataset "
        "dentro de un contexto proporcionado por el usuario."
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


# 🛠️ Configuración para que la app ocupe TODO el ancho de la pantalla
st.set_page_config(layout="wide")

st.title("Extracción de Contexto y Enlace")

# Inicializar estado de sesión para almacenar análisis, contextos y metadatos
if 'analisis_datasets' not in st.session_state:
    st.session_state.analisis_datasets = {}
if 'contextos_datasets' not in st.session_state:
    st.session_state.contextos_datasets = {}
if 'metadatos_articulos_editados' not in st.session_state:
    st.session_state.metadatos_articulos_editados = {}
if 'textos_articulos' not in st.session_state:
    st.session_state.textos_articulos = {}

# --- SECCIÓN 1: DATASETS ---
st.header("1. Datasets")

archivos_a = st.file_uploader("Sube uno o varios datasets", type=["csv", "xlsx"], key="uploader_a", accept_multiple_files=True)

# Diccionario para almacenar los dataframes cargados de la sección A
datasets_dict = {}

if archivos_a:
    st.success(f"¡{len(archivos_a)} dataset(s) cargado(s) con éxito!")
    for archivo in archivos_a:
        # 1. Verificar si es Excel
        if archivo.name.endswith(('.xlsx', '.xls')):
            datasets_dict[archivo.name] = pd.read_excel(archivo)
        
        # 2. Si es CSV, probar diferentes codificaciones comunes
        else:
            try:
                # Intentar primero con la estándar
                datasets_dict[archivo.name] = pd.read_csv(archivo, encoding='utf-8')
            except UnicodeDecodeError:
                try:
                    # Si falla, intentar con la codificación típica de Excel en español
                    datasets_dict[archivo.name] = pd.read_csv(archivo, encoding='latin-1')
                except Exception as e:
                    st.error(f"No se pudo leer el archivo {archivo.name}: {e}")

    # Generar análisis automático para cada dataset
    for dataset_name, df in datasets_dict.items():
        # Solo generar si aún no existe el análisis
        if dataset_name not in st.session_state.analisis_datasets:
            with st.spinner(f"Analizando {dataset_name}..."):
                columnas_y_tipos = df.dtypes.to_string()
                muestra_datos = df.head(5).to_string()
                
                prompt_sistema = (
                    "Eres un experto científico de datos. Tu objetivo es explicar la estructura "
                    "y el propósito de un dataset basándote estrictamente en sus metadatos y una muestra."
                )
                
                prompt_usuario = f"""
                Analiza el archivo '{dataset_name}'.
                
                Columnas y tipos de datos:
                {columnas_y_tipos}
                
                Muestra de las primeras 5 filas:
                {muestra_datos}
                
                Genera una respuesta en español estructurada con:
                1. **Propósito General:** ¿Para qué sirve este archivo y qué mide o registra en general?
                2. **Explicación de Campos:** Un desglose rápido de qué significa cada columna basándote en su nombre y valores.

                hazlo con el minimo de palabras posible, directo al grano, sin suposiciones ni información adicional que no esté en los datos.
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
                    st.session_state.analisis_datasets[dataset_name] = respuesta.choices[0].message.content
                except Exception as e:
                    st.session_state.analisis_datasets[dataset_name] = f"Error al analizar: {e}"
    
    # Selector para visualizar análisis individual
    if st.session_state.analisis_datasets:
        st.markdown("---")
        st.subheader("📋 Ver Análisis Individual de Datasets")
        dataset_seleccionado = st.selectbox(
            "Selecciona un dataset para ver su análisis:",
            options=list(st.session_state.analisis_datasets.keys()),
            key="select_dataset_analisis"
        )
        
        if dataset_seleccionado:
            st.info("💡 **Análisis de Groq:**")
            st.markdown(st.session_state.analisis_datasets[dataset_seleccionado])
            
            # Campo de contexto específico para este dataset
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


st.markdown("---") 


# --- SECCIÓN 2: ARTÍCULOS ---
st.header("2. Artículos")

archivos_b = st.file_uploader("Sube uno o varios artículos (PDF)", type=["pdf"], key="uploader_b", accept_multiple_files=True)

# Diccionarios para almacenar el texto y los metadatos de los artículos
articulos_dict = {}
articulos_meta_dict = {}

if archivos_b:
    st.success(f"¡{len(archivos_b)} artículo(s) PDF cargado(s) con éxito!")
    for archivo in archivos_b:
        try:
            # Guardar los bytes del PDF
            archivo.seek(0)
            pdf_bytes = archivo.read()
            
            lector_pdf = pypdf.PdfReader(archivo)
            
            # 1. Extraer texto del PDF (primeras páginas)
            texto_pdf = ""
            num_paginas_extraer = min(3, len(lector_pdf.pages))
            for i in range(num_paginas_extraer):
                try:
                    texto_pdf += f"\n--- Página {i+1} ---\n"
                    texto_pdf += lector_pdf.pages[i].extract_text()
                except:
                    texto_pdf += f"\n[No se pudo extraer texto de la página {i+1}]\n"
            
            # Almacenar texto y bytes
            if 'textos_articulos' not in st.session_state:
                st.session_state.textos_articulos = {}
            st.session_state.textos_articulos[archivo.name] = texto_pdf
            
            # 2. Metadatos iniciales (serán sobrescritos por Groq)
            meta = lector_pdf.metadata
            articulos_meta_dict[archivo.name] = {
                "Título del documento": meta.title if meta and meta.title else "No especificado",
                "Autor": meta.author if meta and meta.author else "No especificado",
                "Creador/Software": meta.creator if meta and meta.creator else "Desconocido",
                "Número de Páginas": len(lector_pdf.pages)
            }
            
            articulos_dict[archivo.name] = pdf_bytes
            
        except Exception as e:
            st.error(f"No se pudo leer el PDF {archivo.name}: {e}")

    # Mostrar vista previa y metadatos editable de Artículos PDF
    articulo_visualizar = st.selectbox("Editar metadatos del Artículo:", list(articulos_dict.keys()))
    if articulo_visualizar:
        # Procesar con Groq si no está hecho
        if articulo_visualizar not in st.session_state.metadatos_articulos_editados:
            if articulo_visualizar in st.session_state.textos_articulos:
                texto_pdf = st.session_state.textos_articulos[articulo_visualizar][:4000]
                
                with st.spinner(f"Extrayendo metadatos de {articulo_visualizar} con IA..."):
                    prompt = f"""
                    Analiza este fragmento de un documento académico y extrae:
                    1. Título completo del documento
                    2. Lista de todos los autores en formato [autor1,autor2,autor3]
                    
                    Si no encuentras información clara, deduce lo que puedas del contexto.
                    
                    Responde SOLO en formato JSON sin explicaciones adicionales:
                    {{
                        "titulo": "Título completo del documento",
                        "autores": "Nombre Apellido,Nombre Apellido,Nombre Apellido"
                    }}
                    
                    Texto:
                    {texto_pdf}
                    """
                    
                    try:
                        respuesta = client.chat.completions.create(
                            model=MODELO_LLM,
                            messages=[{"role": "user", "content": prompt}],
                            response_format={"type": "json_object"},
                            temperature=0.2
                        )
                        
                        resultado = json.loads(respuesta.choices[0].message.content)
                        metadatos_nuevos = {
                            "Título del documento": resultado.get("titulo", ""),
                            "Autor": resultado.get("autores", "")
                        }
                        st.session_state.metadatos_articulos_editados[articulo_visualizar] = metadatos_nuevos
                        
                        # Detectar cambios significativos
                        metadatos_originales = articulos_meta_dict[articulo_visualizar]
                        titulo_original = metadatos_originales.get("Título del documento", "No especificado")
                        titulo_nuevo = metadatos_nuevos.get("Título del documento", "")
                        autor_original = metadatos_originales.get("Autor", "No especificado")
                        autor_nuevo = metadatos_nuevos.get("Autor", "")
                        
                        # Comparar cambios
                        cambio_titulo = titulo_original != titulo_nuevo and titulo_original != "No especificado"
                        cambio_autor = autor_original != autor_nuevo and autor_original != "No especificado"
                        
                        if cambio_titulo or cambio_autor:
                            st.warning("⚠️ **CAMBIOS DETECTADOS EN METADATOS**")
                            with st.expander("🔍 Ver cambios detectados", expanded=True):
                                if cambio_titulo:
                                    st.markdown("**Título:**")
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        st.write(f"**Original:** {titulo_original}")
                                    with col2:
                                        st.write(f"**Nuevo:** {titulo_nuevo}")
                                
                                if cambio_autor:
                                    st.markdown("**Autores:**")
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        st.write(f"**Original:** {autor_original}")
                                    with col2:
                                        st.write(f"**Nuevo:** {autor_nuevo}")
                        else:
                            st.success("✅ Metadatos extraídos correctamente con IA")
                    except Exception as e:
                        st.session_state.metadatos_articulos_editados[articulo_visualizar] = {
                            "Título del documento": articulos_meta_dict[articulo_visualizar].get("Título del documento", ""),
                            "Autor": articulos_meta_dict[articulo_visualizar].get("Autor", "")
                        }
                        st.error(f"Error al procesar con IA: {e}")
            else:
                st.session_state.metadatos_articulos_editados[articulo_visualizar] = {
                    "Título del documento": articulos_meta_dict[articulo_visualizar].get("Título del documento", ""),
                    "Autor": articulos_meta_dict[articulo_visualizar].get("Autor", "")
                }
        
        # Sección de edición de metadatos
        st.markdown("---")
        with st.expander("✏️ Editar Metadatos del Artículo", expanded=True):
            titulo_editado = st.text_input(
                "Título del documento:",
                value=st.session_state.metadatos_articulos_editados[articulo_visualizar].get("Título del documento", ""),
                key=f"titulo_{articulo_visualizar}"
            )
            st.session_state.metadatos_articulos_editados[articulo_visualizar]["Título del documento"] = titulo_editado
            
            autor_editado = st.text_input(
                "Autores (formato: [autor1,autor2,autor3]):",
                value=st.session_state.metadatos_articulos_editados[articulo_visualizar].get("Autor", ""),
                key=f"autor_{articulo_visualizar}"
            )
            st.session_state.metadatos_articulos_editados[articulo_visualizar]["Autor"] = autor_editado
            
            st.success("✅ Los cambios se guardan automáticamente")

st.markdown("---")
contexto_manual = st.text_area(
    "Contexto general para los datasets (útil si no tienes documento asociado):",
    height=150
)

st.markdown("---")

# --- SECCIÓN 3: GUARDAR COMBINACIONES ---
if datasets_dict or st.session_state.analisis_datasets:
    st.header("💾 3. Guardar Combinaciones Resultantes")
    
    # Resumen de lo que se va a guardar
    st.subheader("📝 Resumen de lo que se guardará:")
    resumen = f"""
    - **Datasets:** {len(datasets_dict)} archivo(s)
    - **Análisis generados:** {len(st.session_state.analisis_datasets)} análisis
    - **Contextos específicos:** {len([c for c in st.session_state.contextos_datasets.values() if c])} contextos definidos
    - **Documentos PDF:** {len(articulos_dict)} PDF(s)
    """
    st.info(resumen)
    
    # Inicializar lista de carpetas destino
    if 'carpetas_destino' not in st.session_state:
        st.session_state.carpetas_destino = []
    
    # Selector para número de carpetas
    num_carpetas = st.number_input(
        "¿Cuántas carpetas deseas crear?",
        min_value=1,
        max_value=10,
        value=1,
        step=1
    )
    
    # Ajustar lista de carpetas según número seleccionado
    if len(st.session_state.carpetas_destino) < num_carpetas:
        st.session_state.carpetas_destino.extend([{"nombre": "", "ruta": "", "contextos_editable": {}} for _ in range(num_carpetas - len(st.session_state.carpetas_destino))])
    elif len(st.session_state.carpetas_destino) > num_carpetas:
        st.session_state.carpetas_destino = st.session_state.carpetas_destino[:num_carpetas]
    
    # Formulario dinámico para cada carpeta
    st.subheader("📁 Configurar Carpetas de Destino")
    for idx in range(num_carpetas):
        with st.expander(f"Carpeta {idx + 1}", expanded=(idx == 0)):
            col1, col2 = st.columns(2)
            
            with col1:
                nombre = st.text_input(
                    f"Nombre carpeta {idx + 1}:",
                    value=st.session_state.carpetas_destino[idx]["nombre"],
                    placeholder="proyecto_investigacion",
                    key=f"nombre_carpeta_{idx}"
                )
                st.session_state.carpetas_destino[idx]["nombre"] = nombre
            
            with col2:
                ruta = st.text_input(
                    f"Ruta base {idx + 1} (dejar en blanco para escritorio):",
                    value=st.session_state.carpetas_destino[idx]["ruta"],
                    placeholder="C:\\Users\\tu_usuario\\Documentos",
                    key=f"ruta_carpeta_{idx}"
                )
                st.session_state.carpetas_destino[idx]["ruta"] = ruta
            
            # Selector de archivos a guardar
            st.markdown(f"**Archivos a guardar en Carpeta {idx + 1}:**")
            
            col_a, col_b, col_c = st.columns(3)
            
            with col_a:
                guardar_datasets = st.checkbox(
                    "📊 Datasets",
                    value=st.session_state.carpetas_destino[idx].get("guardar_datasets", True),
                    key=f"check_datasets_{idx}"
                )
                st.session_state.carpetas_destino[idx]["guardar_datasets"] = guardar_datasets
            
            with col_b:
                guardar_pdfs = st.checkbox(
                    "📄 Artículos PDF",
                    value=st.session_state.carpetas_destino[idx].get("guardar_pdfs", True),
                    key=f"check_pdfs_{idx}"
                )
                st.session_state.carpetas_destino[idx]["guardar_pdfs"] = guardar_pdfs
            
            with col_c:
                guardar_metadatos = st.checkbox(
                    "📋 Metadatos",
                    value=st.session_state.carpetas_destino[idx].get("guardar_metadatos", True),
                    key=f"check_metadatos_{idx}"
                )
                st.session_state.carpetas_destino[idx]["guardar_metadatos"] = guardar_metadatos
            
            # Selector de datasets específicos (si hay)
            if datasets_dict and guardar_datasets:
                # Inicializar contextos_editable si no existe
                if "contextos_editable" not in st.session_state.carpetas_destino[idx]:
                    st.session_state.carpetas_destino[idx]["contextos_editable"] = {}
                
                st.markdown("Selecciona qué datasets guardar:")
                datasets_seleccionados = st.multiselect(
                    f"Datasets para Carpeta {idx + 1}:",
                    options=list(datasets_dict.keys()),
                    default=list(datasets_dict.keys()),
                    key=f"select_datasets_{idx}"
                )
                st.session_state.carpetas_destino[idx]["datasets_seleccionados"] = datasets_seleccionados
                
                # Generar contextos automáticos al seleccionar datasets
                pdfs_a_guardar = st.session_state.carpetas_destino[idx].get("pdfs_seleccionados", list(articulos_dict.keys()))
                
                for dataset_name in datasets_seleccionados:
                    if dataset_name not in st.session_state.carpetas_destino[idx]["contextos_editable"]:
                        resumen_auto = ""
                        relacion_auto = ""
                        
                        if pdfs_a_guardar:
                            resumenes_papers = []
                            for pdf_name in pdfs_a_guardar:
                                if pdf_name in st.session_state.textos_articulos:
                                    texto_pdf = st.session_state.textos_articulos[pdf_name]
                                    try:
                                        prompt_resumen = f"""
                                        Lee este paper académico completo y genera un resumen muy breve (2-3 líneas máximo) 
                                        sobre el tema principal y propósito del paper.
                                        
                                        IMPORTANTE: Responde con este formato exacto:
                                        resumen: [aquí va el contenido del resumen del paper]
                                        relacion con el dataset: [aquí va la relación del dataset con el paper]
                                        
                                        Texto:
                                        {texto_pdf}
                                        """
                                        respuesta_resumen = client.chat.completions.create(
                                            model=MODELO_LLM,
                                            messages=[{"role": "user", "content": prompt_resumen}],
                                            temperature=0.3
                                        )
                                        respuesta = respuesta_resumen.choices[0].message.content.strip()
                                        resumenes_papers.append(respuesta)
                                    except:
                                        pass
                            
                            if resumenes_papers:
                                resumen_auto = "\n\n".join(resumenes_papers)
                        
                        st.session_state.carpetas_destino[idx]["contextos_editable"][dataset_name] = {
                            "resumen": resumen_auto,
                            "relacion_dataset": relacion_auto
                        }
            
            # Selector de PDFs específicos (si hay)
            if articulos_dict and guardar_pdfs:
                st.markdown("Selecciona qué artículos guardar:")
                pdfs_seleccionados = st.multiselect(
                    f"Artículos para Carpeta {idx + 1}:",
                    options=list(articulos_dict.keys()),
                    default=list(articulos_dict.keys()),
                    key=f"select_pdfs_{idx}"
                )
                st.session_state.carpetas_destino[idx]["pdfs_seleccionados"] = pdfs_seleccionados
            
            # Editar contextos de datasets
            if datasets_dict and guardar_datasets:
                st.markdown("---")
                st.markdown(f"**📝 Editar Contextos por Dataset:**")
                
                datasets_a_guardar = st.session_state.carpetas_destino[idx].get("datasets_seleccionados", [])
                
                if datasets_a_guardar:
                    for dataset_name in datasets_a_guardar:
                        with st.expander(f"📊 {dataset_name}", expanded=False):
                            resumen = st.text_area(
                                "Resumen:",
                                value=st.session_state.carpetas_destino[idx]["contextos_editable"][dataset_name].get("resumen", ""),
                                height=60,
                                key=f"resumen_{idx}_{dataset_name}"
                            )
                            st.session_state.carpetas_destino[idx]["contextos_editable"][dataset_name]["resumen"] = resumen
                            
                            relacion = st.text_area(
                                "Relación con el dataset:",
                                value=st.session_state.carpetas_destino[idx]["contextos_editable"][dataset_name].get("relacion_dataset", ""),
                                height=60,
                                key=f"relacion_{idx}_{dataset_name}"
                            )
                            st.session_state.carpetas_destino[idx]["contextos_editable"][dataset_name]["relacion_dataset"] = relacion
                else:
                    st.info("ℹ️ Selecciona datasets arriba para editar contextos")
    
    if st.button("💾 Guardar en Todas las Carpetas", type="primary"):
        carpetas_guardadas = []
        errores = []
        
        for idx, config_carpeta in enumerate(st.session_state.carpetas_destino):
            try:
                nombre_carpeta = config_carpeta["nombre"] or f"proyecto_{idx + 1}"
                ruta_base = config_carpeta["ruta"]
                
                # Determinar ruta final
                if ruta_base:
                    ruta_final = Path(ruta_base) / nombre_carpeta
                else:
                    escritorio = Path.home() / "Desktop"
                    ruta_final = escritorio / nombre_carpeta
                
                # Crear carpeta
                ruta_final.mkdir(parents=True, exist_ok=True)
                
                # 1. Guardar datasets seleccionados
                if config_carpeta.get("guardar_datasets", True):
                    carpeta_datasets = ruta_final / "datasets"
                    carpeta_datasets.mkdir(exist_ok=True)
                    
                    datasets_a_guardar = config_carpeta.get("datasets_seleccionados", list(datasets_dict.keys()))
                    for dataset_name in datasets_a_guardar:
                        if dataset_name in datasets_dict:
                            df = datasets_dict[dataset_name]
                            ruta_dataset = carpeta_datasets / dataset_name
                            if dataset_name.endswith('.csv'):
                                df.to_csv(ruta_dataset, index=False)
                            else:
                                df.to_excel(ruta_dataset, index=False)
                
                # 2. Guardar PDFs seleccionados
                if config_carpeta.get("guardar_pdfs", True) and articulos_dict:
                    carpeta_pdfs = ruta_final / "articulos"
                    carpeta_pdfs.mkdir(exist_ok=True)
                    
                    pdfs_a_guardar = config_carpeta.get("pdfs_seleccionados", list(articulos_dict.keys()))
                    for pdf_name in pdfs_a_guardar:
                        if pdf_name in articulos_dict and articulos_dict[pdf_name]:
                            ruta_pdf = carpeta_pdfs / pdf_name
                            with open(ruta_pdf, 'wb') as f:
                                f.write(articulos_dict[pdf_name])
                
                # 3. Guardar metadatos
                if config_carpeta.get("guardar_metadatos", True):
                    metadatos = {
                        "datasets": {},
                        "articulos": {},
                        "contexto_general": contexto_manual if 'contexto_manual' in locals() else "",
                        "fecha_creacion": str(pd.Timestamp.now())
                    }
                    
                    # Agregar análisis y contextos específicos solo de datasets guardados
                    datasets_a_guardar = config_carpeta.get("datasets_seleccionados", list(datasets_dict.keys()))
                    pdfs_a_guardar = config_carpeta.get("pdfs_seleccionados", list(articulos_dict.keys()))
                    
                    for dataset_name in datasets_a_guardar:
                        if dataset_name in datasets_dict:
                            # Verificar si hay contexto editado en la carpeta
                            contextos_editable = config_carpeta.get("contextos_editable", {})
                            
                            if dataset_name in contextos_editable:
                                resumen_edit = contextos_editable[dataset_name].get("resumen", "").strip()
                                relacion_edit = contextos_editable[dataset_name].get("relacion_dataset", "").strip()
                                
                                if resumen_edit or relacion_edit:
                                    contexto_final = f"resumen: {resumen_edit}\nrelacion con el dataset: {relacion_edit}" if resumen_edit and relacion_edit else (resumen_edit or relacion_edit)
                                else:
                                    # Si no hay contexto editado, usar específico > general > generar automático
                                    contexto_especifico = st.session_state.contextos_datasets.get(dataset_name, "")
                                    contexto_final = contexto_especifico if contexto_especifico else contexto_manual
                            else:
                                # Usar específico > general
                                contexto_especifico = st.session_state.contextos_datasets.get(dataset_name, "")
                                contexto_final = contexto_especifico if contexto_especifico else contexto_manual
                            
                            # Si no hay contexto en ningún lugar, generar uno basado en resúmenes de papers
                            if not contexto_final and pdfs_a_guardar:
                                resumenes_papers = []
                                for pdf_name in pdfs_a_guardar:
                                    if pdf_name in st.session_state.textos_articulos:
                                        texto_pdf = st.session_state.textos_articulos[pdf_name]
                                        try:
                                            prompt_resumen = f"""
                                            Lee este paper académico completo y genera un resumen muy breve (2-3 líneas máximo) 
                                            sobre el tema principal y propósito del paper.
                                            
                                            IMPORTANTE: Responde con este formato exacto:
                                            resumen: [aquí va el contenido del resumen del paper]
                                            relacion con el dataset: [aquí va la relación del dataset con el paper]
                                            
                                            Texto:
                                            {texto_pdf}
                                            """
                                            respuesta_resumen = client.chat.completions.create(
                                                model=MODELO_LLM,
                                                messages=[{"role": "user", "content": prompt_resumen}],
                                                temperature=0.3
                                            )
                                            resumen = respuesta_resumen.choices[0].message.content.strip()
                                            if resumen:
                                                resumenes_papers.append(resumen)
                                        except:
                                            pass
                                
                                if resumenes_papers:
                                    contexto_final = "\n\n".join(resumenes_papers)
                            
                            metadatos["datasets"][dataset_name] = {
                                "analisis": st.session_state.analisis_datasets.get(dataset_name, ""),
                                "contexto": contexto_final,
                                "articulos_asociados": pdfs_a_guardar
                            }
                    
                    # Agregar metadatos editados de artículos
                    for pdf_name in pdfs_a_guardar:
                        if pdf_name in articulos_dict:
                            metadatos["articulos"][pdf_name] = st.session_state.metadatos_articulos_editados.get(pdf_name, articulos_meta_dict.get(pdf_name, {}))
                    
                    # Guardar metadatos
                    ruta_metadatos = ruta_final / "metadatos.json"
                    with open(ruta_metadatos, 'w', encoding='utf-8') as f:
                        json.dump(metadatos, f, indent=2, ensure_ascii=False)
                
                carpetas_guardadas.append(str(ruta_final))
                
            except Exception as e:
                errores.append(f"Carpeta {idx + 1}: {e}")
        
        # Mostrar resultados
        if carpetas_guardadas:
            st.success(f"✅ Se guardaron {len(carpetas_guardadas)} carpeta(s):")
            for ruta in carpetas_guardadas:
                st.write(f"📁 {ruta}")
            st.balloons()
        
        if errores:
            st.error("❌ Errores:")
            for error in errores:
                st.write(error)