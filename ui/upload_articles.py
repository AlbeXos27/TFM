import streamlit as st
from client_ia.request_Groq import encontrar_autores_ia
from utils.extract_abstract import extraer_contexto_pdf
from utils.orcid import actualizar_orcid_seleccionado, buscar_en_orcid_real


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
        
        articulo_visualizar = st.selectbox("Selecciona un Artículo para gestionar sus metadatos y autores:", list(articulos_dict.keys()))
        
        if articulo_visualizar:
            datos_actuales = st.session_state.metadatos_articulos_editados[articulo_visualizar]
            
            if not datos_actuales.get("autores_detectados") and "titulo" not in datos_actuales:
                if articulo_visualizar in st.session_state.textos_articulos:
                    encontrar_autores_ia(st.session_state.textos_articulos[articulo_visualizar], datos_actuales, articulo_visualizar, st)

            st.markdown("---")
            
            st.subheader("📄 Información General del Artículo")
            titulo_editado = st.text_input("Título del documento:", value=datos_actuales.get("titulo", ""), key=f"tit_{articulo_visualizar}")
            datos_actuales["titulo"] = titulo_editado
            
            # MODIFICACIÓN AQUÍ: Asignamos el valor del toggle directamente a datos_actuales
            subir_archivo = st.toggle("Subir archivo", value=datos_actuales.get("subir_archivo", True), key=f"tog_{articulo_visualizar}")
            datos_actuales["subir_archivo"] = subir_archivo # Guardamos el booleano (True/False)
            
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
            
            if "autores_finales_seleccionados" not in datos_actuales:
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
                                st.rerun()
                        
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
                            st.rerun()
            else:
                st.info("No se han detectado autores para este artículo. Puedes añadir uno manualmente arriba.")

    st.markdown("---")