import streamlit as st
from client_ia.request_IA import extraer_metadatos_articles
from ui.upload_dataset import corregir_frase
from utils.extract_abstract import extraer_contexto_pdf
from utils.orcid import actualizar_orcid_seleccionado, buscar_en_orcid_real
from utils.licencias import CATALOGO_LICENCIAS, LICENCIA_POR_DEFECTO, nombre_legible
import json
from deep_translator import GoogleTranslator

def ui_upload_articles(articulos_dict, st):
    archivos_b = st.file_uploader("Sube uno o varios artículos (PDF)", type=["pdf"], key="uploader_b", accept_multiple_files=True)
    
    if archivos_b:
        nuevos = [archivo for archivo in archivos_b if archivo.name not in articulos_dict]
        if nuevos:
            st.success(f"¡{len(nuevos)} artículo(s) PDF cargado(s) con éxito!")
            for archivo in nuevos:
                extraer_contexto_pdf(archivo, articulos_dict, st)
        elif archivos_b:
            st.info("Los artículos seleccionados ya están cargados.")

        # Procesar metadatos (autores/título) automáticamente una única vez por artículo
        for nombre_articulo in articulos_dict:
            datos_articulo = st.session_state.metadatos_articulos_editados[nombre_articulo]
            if not datos_articulo.get("autores_detectados") and "title" not in datos_articulo:
                if nombre_articulo in st.session_state.textos_articulos:
                    with st.spinner(f"Analizando metadatos y autores de {nombre_articulo}..."):
                        try:
                            resultado_ia = json.loads(
                                extraer_metadatos_articles(st, nombre_articulo, st.session_state.textos_articulos[nombre_articulo])
                            )
                            resultado_ia["autores_detectados"] = resultado_ia.pop("autores", [])
                        except Exception as e:
                            resultado_ia = {"title": nombre_articulo, "autores_detectados": []}
                            st.warning(f"⚠️ No se pudieron analizar los metadatos de {nombre_articulo} automáticamente: {e}")
                        datos_articulo.update(resultado_ia)

        articulo_visualizar = st.selectbox("Selecciona un Artículo para gestionar sus metadatos y autores:", list(articulos_dict.keys()))

        if articulo_visualizar:
            datos_actuales = st.session_state.metadatos_articulos_editados[articulo_visualizar]
            st.markdown("---")
            
            st.subheader("📄 Información General del Artículo")
            titulo_editado = st.text_input("Título del documento:", value=datos_actuales.get("title", ""), key=f"tit_{articulo_visualizar}")
            datos_actuales["title"] = titulo_editado
            
            # MODIFICACIÓN AQUÍ: Asignamos el valor del toggle directamente a datos_actuales
            subir_archivo = st.toggle("Subir archivo", value=datos_actuales.get("subir_archivo", True), key=f"tog_{articulo_visualizar}")
            datos_actuales["subir_archivo"] = subir_archivo # Guardamos el booleano (True/False)
            
            contexto_editado = st.text_area("Resumen de este artículo:", value=datos_actuales.get("resumen", ""), height=100, key=f"ctx_{articulo_visualizar}")
            datos_actuales["contexto_unico"] = contexto_editado

            st.markdown("#### 📜 Licencia del Artículo")
            ids_licencias_art = [l["id"] for l in CATALOGO_LICENCIAS]
            licencia_actual_art = datos_actuales.get("licencia", LICENCIA_POR_DEFECTO)
            if licencia_actual_art not in ids_licencias_art:
                licencia_actual_art = LICENCIA_POR_DEFECTO
            licencia_art = st.selectbox(
                "Licencia bajo la que se publica este artículo:",
                options=ids_licencias_art,
                format_func=nombre_legible,
                index=ids_licencias_art.index(licencia_actual_art),
                key=f"licencia_art_{articulo_visualizar}",
            )
            datos_actuales["licencia"] = licencia_art

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
            
            if not datos_actuales.get("autores_finales_seleccionados"):
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

                st.markdown("<br>", unsafe_allow_html=True)
                
                st.markdown("#### 🔍 Identificador de ORCID por Investigador")
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
                        
                        options_actuales = datos_actuales["resultados_busqueda_api"].get(autor, ["Selecciona un resultado del listado..."])
                        sb_key = f"select_orcid_list_{articulo_visualizar}_{autor}"
                        
                        st.selectbox(
                            "Coincidencias encontradas en ORCID:",
                            options=options_actuales,
                            key=sb_key,
                            on_change=actualizar_orcid_seleccionado,
                            args=(articulo_visualizar, autor, sb_key,st)
                        )
                        
                        valor_actual_orcid = datos_actuales["orcids_vinculados"].get(autor, "")
                        input_key = f"final_orcid_{articulo_visualizar}_{autor}"
                        
                        if input_key not in st.session_state:
                            st.session_state[input_key] = valor_actual_orcid
                        
                        orcid_confirmado = st.text_input("ORCID Definitivo:", key=input_key)
                        
                        if orcid_confirmado != valor_actual_orcid:
                            datos_actuales["orcids_vinculados"][autor] = orcid_confirmado
                
                st.markdown("#### Temática e idioma del documento: ")
                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    st.text_input("Temática del documento:", value=datos_actuales.get("subject", ""), key=f"subject_{articulo_visualizar}") 
                with col2:
                    NOMBRES_IDIOMAS = {
                        "es": "Español",
                        "en": "Inglés",
                    }
                    codigo_idioma = datos_actuales.get("language", "").strip().lower()
                    idioma_texto = NOMBRES_IDIOMAS.get(codigo_idioma, codigo_idioma)
                    st.text_input(
                        "Idioma del documento:",
                        value=idioma_texto,
                        key=f"idioma_{articulo_visualizar}",
                    )
                with col3:
                    st.text_input("DOI:", value=datos_actuales.get("doi", ""), key=f"doi_{articulo_visualizar}")    
                    
                    
                st.markdown(" #### Comparativa y Control de Palabras clave del documento: ")
                col_meta_kw, col_ia_kw = st.columns(2)
                with col_meta_kw:
                    st.markdown("**📂 Encontrados en Metadatos del PDF (Limpios):**")
                    keywords_pdf = datos_actuales.get("keywords_pdf_metadatos", [])
                    if keywords_pdf:
                        for k in keywords_pdf:
                            st.markdown(f"- `{k}`")
                    else:
                        st.caption("Ninguna registrada en las propiedades del archivo.")
                        
                with col_ia_kw:
                    st.markdown("**🤖 Extraídos por Inteligencia Artificial:**")
                    keywords_ia = datos_actuales.get("keywords", [])
                    keywords_finales_ia = []
                    if keywords_ia:
                        translator = GoogleTranslator(source="auto", target=datos_actuales.get("language", "").strip().lower())

                        for k in keywords_ia:
                            try:
                                kw_traducida = translator.translate(k)
                                keywords_finales_ia.append(
                                    kw_traducida if kw_traducida else k
                                )
                            except Exception:

                                keywords_finales_ia.append(k)

                        for k in keywords_finales_ia:
                            st.markdown(f"- `{k}`")
                            
                st.markdown("#### Palabras Clave Configuradas")

                if not datos_actuales.get("keywords_finales_seleccionadas"):
                    lista_unificada = list(set(keywords_pdf + keywords_finales_ia))
                    datos_actuales["keywords_finales_seleccionadas"] = [k for k in lista_unificada if k]

                key_opciones_kw = f"opciones_kw_{articulo_visualizar}"
                key_ms_kw = f"ms_kw_{articulo_visualizar}"
                key_input_kw = f"input_kw_{articulo_visualizar}"

                # 1. Cargar e inicializar opciones base en session_state (solo si no existen)
                if key_opciones_kw not in st.session_state:
                    st.session_state[key_opciones_kw] = [
                        k for k in datos_actuales["keywords_finales_seleccionadas"] if k
                    ]

                # 2. Inicializar selección activa del multiselect
                if key_ms_kw not in st.session_state:
                    st.session_state[key_ms_kw] = list(st.session_state[key_opciones_kw])

                # 3. Función callback para procesar e insertar el nuevo valor al pulsar Enter
                def agregar_palabra_clave():
                    valor_input = st.session_state[key_input_kw]
                    if valor_input and valor_input.strip():
                        nuevo_corregido = corregir_frase(valor_input, language=datos_actuales.get("language", "").strip().lower())

                        if nuevo_corregido not in st.session_state[key_opciones_kw]:
                            st.session_state[key_opciones_kw].append(nuevo_corregido)

                        if nuevo_corregido not in st.session_state[key_ms_kw]:
                            st.session_state[key_ms_kw].append(nuevo_corregido)

                    st.session_state[key_input_kw] = ""

                # 4. Input para escribir nuevas palabras clave
                st.text_input(
                    "➕ Escribe una nueva palabra clave y pulsa Enter para añadirla:",
                    key=key_input_kw,
                    on_change=agregar_palabra_clave,
                    placeholder="Ej. Machine Learning"
                )

                # 5. Multiselect vinculado por key al session_state
                kw_seleccionadas = st.multiselect(
                    "Palabras Clave del Artículo:",
                    options=st.session_state[key_opciones_kw],
                    key=key_ms_kw
                )

                # 6. Actualizar la estructura de datos principal
                datos_actuales["keywords_finales_seleccionadas"] = kw_seleccionadas
                keywords_actuales = kw_seleccionadas
            
                    
                    
                

    st.markdown("---")