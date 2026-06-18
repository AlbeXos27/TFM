import pandas as pd
import requests
from io import BytesIO, StringIO
from client_ia.request_Groq import generar_contexto_dataset
from utils.orcid import actualizar_orcid_ds, buscar_en_orcid_real

def ui_upload_datasets(datasets_dict, st):
    # Creamos pestañas para los dos métodos de carga
    tab1, tab2 = st.tabs(["📁 Subir archivos locales", "🔗 Cargar desde enlace (URL)"])
    
    archivos_a = []
    
    with tab1:
        archivos_subidos = st.file_uploader(
            "Sube uno o varios datasets", 
            type=["csv", "xlsx", "txt"], 
            key="uploader_a", 
            accept_multiple_files=True
        )
        if archivos_subidos:
            archivos_a.extend(archivos_subidos)

    with tab2:
        url_input = st.text_input(
            "Introduce la URL directa del dataset (CSV, XLSX, TXT):", 
            placeholder="https://ejemplo.com/datos.csv",
            key="uploader_url"
        )
        
        if url_input:
            # Extraemos un nombre simulado para el archivo a partir de la URL
            nombre_sugerido = url_input.split("/")[-1]
            if not nombre_sugerido.endswith(('.csv', '.xlsx', '.xls', '.txt')):
                nombre_sugerido = "dataset_url.csv" # Nombre por defecto si la URL es genérica
            
            # Evitamos descargar repetidamente en cada renderizado usando cache o session_state si ya existe
            if nombre_sugerido not in datasets_dict:
                try:
                    with st.spinner("Descargando archivo desde la URL..."):
                        response = requests.get(url_input, timeout=15)
                        response.raise_for_status() # Lanza error si la descarga falla
                        
                        # Simular el objeto de archivo en memoria usando BytesIO
                        archivo_url = BytesIO(response.content)
                        archivo_url.name = nombre_sugerido
                        archivos_a.append(archivo_url)
                except Exception as e:
                    st.error(f"❌ Error al descargar el archivo desde la URL: {e}")

    # --- PROCESAMIENTO DE ARCHIVOS (Igual para local o URL) ---
    if archivos_a:
        # Nota: Como ahora puede haber mezclas, controlamos mensajes de éxito por separado o globales
        # Para mantener tu flujo, procesamos cada archivo de la lista 'archivos_a'
        for archivo in archivos_a:
            # Evitar reprocesar si ya está cargado en esta ejecución
            if archivo.name in datasets_dict:
                continue
                
            if archivo.name.endswith(('.xlsx', '.xls')):
                try:
                    datasets_dict[archivo.name] = pd.read_excel(archivo)
                    st.toast(f"¡{archivo.name} cargado con éxito desde Excel!")
                except Exception as e:
                    st.error(f"❌ Error al leer Excel {archivo.name}: {e}")
            else:
                try:
                    # Intento 1: Detección automática en UTF-8
                    datasets_dict[archivo.name] = pd.read_csv(
                        archivo, 
                        encoding='utf-8', 
                        sep=None,          
                        engine='python',   
                        on_bad_lines='skip'
                    )
                    st.toast(f"¡{archivo.name} cargado con éxito!")
                except Exception:
                    try:
                        # Si es un objeto BytesIO (de la URL), hay que resetear el puntero para volver a leerlo
                        if hasattr(archivo, 'seek'):
                            archivo.seek(0)
                            
                        # Intento 2: Codificación Latin-1
                        datasets_dict[archivo.name] = pd.read_csv(
                            archivo, 
                            encoding='latin-1', 
                            sep=None, 
                            engine='python', 
                            on_bad_lines='skip'
                        )
                        st.toast(f"¡{archivo.name} cargado con éxito (Latin-1)!")
                    except Exception as e:
                        st.error(f"❌ No se pudo leer el archivo {archivo.name}. Verifica que el formato de texto sea válido. Error: {e}")
                        
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
                                st.rerun()
                else:
                    st.info("No se han detectado autores para este dataset. Puedes añadir uno manualmente arriba.")

    st.markdown("---")