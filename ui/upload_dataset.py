import json
from turtle import st
from spellchecker import SpellChecker
import requests
import pandas as pd
from io import BytesIO, StringIO
from client_ia.request_IA import generar_contexto_dataset
from utils.orcid import actualizar_orcid_ds, buscar_en_orcid_real
from utils.licencias import CATALOGO_LICENCIAS, LICENCIA_POR_DEFECTO, nombre_legible



def corregir_frase(texto,language='es'):
    spell = SpellChecker(language=language)
    if not texto:
        return ""
    texto_limpio = str(texto).replace("_", " ").strip()
    palabras = texto_limpio.split()
    palabras_ok = []
    for p in palabras:
        # Intentamos corregir palabra a palabra
        sugerencia = spell.correction(p.lower())
        palabras_ok.append(sugerencia if sugerencia else p)
    return " ".join(palabras_ok).capitalize()


def ui_upload_datasets(datasets_dict, st):
    # Creamos pestañas para los dos métodos de carga
    tab1, tab2 = st.tabs(["📁 Subir archivos locales", "🔗 Cargar desde enlace (URL)"])
    
    archivos_a = []
    
    with tab1:
        archivos_subidos = st.file_uploader(
            "Sube uno o varios datasets", 
            type=["csv", "xlsx", "txt","json"], 
            key="uploader_a", 
            accept_multiple_files=True
        )
        
        if archivos_subidos:
            archivos_a.extend([archivo for archivo in archivos_subidos if archivo.name not in datasets_dict])
            nuevos = [archivo for archivo in archivos_subidos if archivo.name not in datasets_dict]
            if nuevos:
                st.success(f"¡{len(nuevos)} dataset(s) cargado(s) con éxito!")
            else:
                st.info("Los datasets seleccionados ya están cargados.")

    with tab2:
        url_input = st.text_input(
            "Introduce la URL directa del dataset (CSV, XLSX, TXT, JSON):", 
            placeholder="https://ejemplo.com/datos.csv",
            key="uploader_url"
        )
        
        if url_input:
            # Extraemos un nombre simulado para el archivo a partir de la URL
            nombre_sugerido = url_input.split("/")[-1]
            if not nombre_sugerido.endswith(('.csv', '.xlsx', '.xls', '.txt', '.json')):
                nombre_sugerido = "dataset_url.csv" # Nombre por defecto si la URL es genérica
            
            if nombre_sugerido in datasets_dict:
                st.info("El dataset de la URL ya está cargado.")
            else:
                try:
                    with st.spinner("Descargando archivo desde la URL..."):
                        response = requests.get(url_input, timeout=15)
                        response.raise_for_status() # Lanza error si la descarga falla
                        
                        # Simular el objeto de archivo en memoria usando BytesIO
                        archivo_url = BytesIO(response.content)
                        archivo_url.name = nombre_sugerido
                        archivos_a.append(archivo_url)
                        st.success(f"¡Dataset '{nombre_sugerido}' cargado con éxito desde URL!")
                except Exception as e:
                    st.error(f"❌ Error al descargar el archivo desde la URL: {e}")

    # Para mantener tu flujo, procesamos cada archivo de la lista 'archivos_a'
    for archivo in archivos_a:
        # Evitar reprocesar si ya está cargado en esta ejecución
        if archivo.name in datasets_dict:
            continue        
        datasets_dict[archivo.name] = archivo
                        
    # --- BLOQUE DE ANÁLISIS Y GESTIÓN (Tu código original permanece intacto) ---
    for dataset_name, df in datasets_dict.items():
        if dataset_name not in st.session_state.analisis_datasets:
            with st.spinner(f"Analizando estructura y autores de {dataset_name}..."):
                generar_contexto_dataset(df, dataset_name, st)
    
    if st.session_state.analisis_datasets:
        st.markdown("---")
        st.subheader("📋 Ver y Gestionar Datasets")
        dataset_seleccionado = st.selectbox(
            "Selecciona un dataset para ver su análisis y autores:",
            options=list(st.session_state.analisis_datasets.keys()),
            key="select_dataset_analisis"
        )
        
        if dataset_seleccionado:
            st.subheader(f"Propósito General y Estructura del Dataset: {dataset_seleccionado}")
            contenido = st.session_state.analisis_datasets[dataset_seleccionado]

            # 2. Asegurarte de convertirlo a diccionario (si viene como string)
            if isinstance(contenido, str):
                datos = json.loads(contenido)
            else:
                datos = contenido
                
            st.text_area("Propósito General",value = f"{datos.get('proposito_general', 'No disponible')}", height=100, key=f"proposito_general_{dataset_seleccionado}")
            lista_campos = datos.get("explicacion_campos", [])

            if isinstance(lista_campos, list):
                
                df_campos = pd.DataFrame(lista_campos)
                
                df_campos = df_campos.rename(columns={
                    "campo": "Campo / Columna",
                    "tipo_dato": "Tipo de Dato",
                    "explicacion": "Descripción"
                })
                st.data_editor(df_campos, width='stretch',hide_index=True)
            else:
                st.text_area("Estructura del Dataset",value = f"{datos.get('explicacion_campos', 'No disponible')}", height=100, key=f"explicacion_campos_{dataset_seleccionado}")
            
            st.subheader(f"Posibles Usos y Palabras Clave del Dataset: {dataset_seleccionado}")
            
            # Keys dinámicas por dataset
            key_usos = f"lista_usos_{dataset_seleccionado}"
            key_input_usos = f"input_uso_{dataset_seleccionado}"

            # 1. Cargar e inicializar datos en session_state (solo si no existen)
            if key_usos not in st.session_state:
                usos_raw = datos.get("posibles_uso", [])
                st.session_state[key_usos] = [
                    corregir_frase(u) for u in usos_raw if u
                ]

            # 2. Función callback para procesar el nuevo valor
            def agregar_uso():
                valor_input = st.session_state[key_input_usos]
                if valor_input and valor_input.strip():
                    # Corregimos frase completa palabra por palabra
                    nuevo_corregido = corregir_frase(valor_input)
                    
                    # Añadimos a la lista si no es un duplicado
                    if nuevo_corregido not in st.session_state[key_usos]:
                        st.session_state[key_usos].append(nuevo_corregido)
                        
                # Limpiamos el campo de texto
                st.session_state[key_input_usos] = ""

            # 3. Input para escribir valores nuevos
            st.text_input(
                "➕ Escribe un nuevo uso y pulsa Enter para añadirlo:",
                key=key_input_usos,
                on_change=agregar_uso,
                placeholder="Ej. Análisis de tendencias"
            )

            # 4. Multiselect conectado directamente a la lista de opciones de session_state
            usos_seleccionados = st.multiselect(
                "Posibles Usos del Dataset:",
                options=st.session_state[key_usos],
                default=st.session_state[key_usos],
                key=f"ms_usos_{dataset_seleccionado}"
            )

            # Guardar los datos actualizados en la estructura principal
            datos["posibles_uso"] = usos_seleccionados
            
            key_opciones_kw = f"opciones_kw_{dataset_seleccionado}"
            key_ms_kw = f"ms_kw_{dataset_seleccionado}"
            key_input_kw = f"input_kw_{dataset_seleccionado}"

            # 1. Cargar e inicializar opciones base en session_state (solo si no existen)
            if key_opciones_kw not in st.session_state:
                kws_raw = datos.get("palabras_clave", [])
                st.session_state[key_opciones_kw] = [
                    corregir_frase(k) for k in kws_raw if k
                ]

            # 2. Inicializar selección activa del multiselect
            if key_ms_kw not in st.session_state:
                st.session_state[key_ms_kw] = list(st.session_state[key_opciones_kw])

            # 3. Función callback para procesar e insertar el nuevo valor al pulsar Enter
            def agregar_palabra_clave():
                valor_input = st.session_state[key_input_kw]
                if valor_input and valor_input.strip():
                    # Corregir tildes y ortografía palabra por palabra
                    nuevo_corregido = corregir_frase(valor_input)
                    
                    # Añadir a las opciones disponibles
                    if nuevo_corregido not in st.session_state[key_opciones_kw]:
                        st.session_state[key_opciones_kw].append(nuevo_corregido)
                        
                    # Añadir directamente a la lista de seleccionadas activas
                    if nuevo_corregido not in st.session_state[key_ms_kw]:
                        st.session_state[key_ms_kw].append(nuevo_corregido)
                        
                # Limpiar el input de texto
                st.session_state[key_input_kw] = ""

            # 4. Input para escribir nuevas palabras clave
            st.text_input(
                "➕ Escribe una nueva palabra clave y pulsa Enter para añadirla:",
                key=key_input_kw,
                on_change=agregar_palabra_clave,
                placeholder="Ej. Inteligencia artificial"
            )

            # 5. Multiselect vinculado por key al session_state
            kw_seleccionadas = st.multiselect(
                "Palabras Clave del Dataset:",
                options=st.session_state[key_opciones_kw],
                key=key_ms_kw
            )

            # 6. Actualizar la estructura de datos principal
            datos["palabras_clave"] = kw_seleccionadas
            
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
                
            st.markdown("#### 👥 Autores / Creadores del Dataset")
            datos_ds_actuales = st.session_state.metadatos_datasets_editados[dataset_seleccionado]
            datos_ds_actuales.setdefault("autores_finales_seleccionados", [])
            datos_ds_actuales.setdefault("orcids_vinculados", {})
            datos_ds_actuales.setdefault("resultados_busqueda_api", {})

            st.markdown("#### 📜 Licencia del Dataset")
            ids_licencias_ds = [l["id"] for l in CATALOGO_LICENCIAS]
            licencia_actual_ds = datos_ds_actuales.get("licencia", LICENCIA_POR_DEFECTO)
            if licencia_actual_ds not in ids_licencias_ds:
                licencia_actual_ds = LICENCIA_POR_DEFECTO
            licencia_ds = st.selectbox(
                "Licencia bajo la que se publican estos datos:",
                options=ids_licencias_ds,
                format_func=nombre_legible,
                index=ids_licencias_ds.index(licencia_actual_ds),
                key=f"licencia_ds_{dataset_seleccionado}",
            )
            datos_ds_actuales["licencia"] = licencia_ds

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

                st.markdown("##### 🔍 Identificador ORCID para Creadores de Datasets")
                for autor_ds in autores_ds_actuales:
                    if autor_ds not in datos_ds_actuales.get("resultados_busqueda_api", {}):
                        with st.spinner(f"Buscando '{autor_ds}' en ORCID..."):
                            datos_ds_actuales.setdefault("resultados_busqueda_api", {})[autor_ds] = buscar_en_orcid_real(autor_ds)
                    
                    with st.expander(f"Gestionar ORCID para creador: {autor_ds}", expanded=False):
                        sb_key_ds = f"select_orcid_ds_{dataset_seleccionado}_{autor_ds}"

                        st.selectbox(
                            "Coincidencias encontradas:",
                            options=datos_ds_actuales["resultados_busqueda_api"].get(autor_ds, ["Selecciona..."]),
                            key=sb_key_ds,
                            on_change=actualizar_orcid_ds,
                            args=(dataset_seleccionado, autor_ds, sb_key_ds, st)
                        )
                        
                        input_key_ds = f"final_orcid_ds_{dataset_seleccionado}_{autor_ds}"
                        if input_key_ds not in st.session_state:
                            st.session_state[input_key_ds] = datos_ds_actuales["orcids_vinculados"].get(autor_ds, "")
                        
                        orcid_conf = st.text_input("ORCID Creador Definitivo:", key=input_key_ds)
                        if orcid_conf != datos_ds_actuales["orcids_vinculados"].get(autor_ds, ""):
                            datos_ds_actuales["orcids_vinculados"][autor_ds] = orcid_conf
            else:
                st.info("No se han detectado autores para este dataset. Puedes añadir uno manualmente arriba.")

    st.markdown("---")