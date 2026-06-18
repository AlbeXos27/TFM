from upload_platform.upload_to_platform import upload_files_to_dataverse
from utils.creacion_embedding import procesar_y_estructurar_indice
from utils.save_json import guardar_json
from utils.union_context import unir_contextos
from client_ia.request_Groq import mapeo_relaciones_cruzadas, relacion_dataset_contexto, generar_altmetrics
from ui.generate_altmetrics import generar_ui_altmetrics
from upload_platform.upload_to_platform import upload_files_to_dataverse



def ui_join_context_dataset(datasets_dict, articulos_dict, st):
    
    st.header("3. Combinaciones Resultantes y Altmetrics")
    
    if 'carpetas_destino' not in st.session_state:
        st.session_state.carpetas_destino = []
    
    num_carpetas = st.number_input("¿Cuántas carpetas deseas crear?", min_value=1, max_value=10, value=1, step=1)
    
    if len(st.session_state.carpetas_destino) < num_carpetas:
        st.session_state.carpetas_destino.extend([{"nombre": "", "ruta": "", "relaciones_cruzadas": {}, "altmetrics": {}} for _ in range(num_carpetas - len(st.session_state.carpetas_destino))])
    elif len(st.session_state.carpetas_destino) > num_carpetas:
        st.session_state.carpetas_destino = st.session_state.carpetas_destino[:num_carpetas]
    
    for idx in range(num_carpetas):
        with st.expander(f"📁 Configurar Carpeta {idx + 1}", expanded=True):
            nombre = st.text_input(f"Nombre carpeta {idx + 1}:", value=st.session_state.carpetas_destino[idx]["nombre"], key=f"n_carp_{idx}")
            st.session_state.carpetas_destino[idx]["nombre"] = nombre

            datasets_seleccionados = st.multiselect(f"Datasets para Carpeta {idx + 1}:", options=list(datasets_dict.keys()), default=list(datasets_dict.keys()), key=f"sel_d_{idx}")
            pdfs_seleccionados = st.multiselect(f"Artículos para Carpeta {idx + 1} (Opcional):", options=list(articulos_dict.keys()), default=list(articulos_dict.keys()), key=f"sel_p_{idx}")
            
            st.session_state.carpetas_destino[idx]["datasets_seleccionados"] = datasets_seleccionados
            st.session_state.carpetas_destino[idx]["pdfs_seleccionados"] = pdfs_seleccionados
            
            if pdfs_seleccionados:
                estrategia_contexto = st.radio(
                    f"🎯 Estrategia de Contexto para IA (Carpeta {idx + 1}):",
                    options=["Solo Artículo", "Solo Contexto Manual del Dataset", "🧬 Mezclar Ambos Contextos (Artículo + Manual)"],
                    index=2,
                    key=f"est_ctx_{idx}"
                )

            # 🤖 PROCESADOR DE INTELIGENCIA ARTIFICIAL DE RELACIONES + ALTMETRICS
            if datasets_seleccionados:
                if st.button(f"🤖 Ejecutar Análisis Científico e Impacto Altmetrics (Carpeta {idx + 1})", key=f"btn_ia_{idx}"):
                    st.session_state.carpetas_destino[idx].setdefault("relaciones_cruzadas", {})
                    st.session_state.carpetas_destino[idx].setdefault("altmetrics", {})
                    
                    # Parte A: Relaciones Cruzadas Académicas
                    for d_name in datasets_seleccionados:
                        df = datasets_dict[d_name]
                        contexto_dataset_manual = st.session_state.contextos_datasets.get(d_name, "").strip()
                        
                        if pdfs_seleccionados:
                            for p_name in pdfs_seleccionados:
                                st.session_state.carpetas_destino[idx]["relaciones_cruzadas"].setdefault(p_name, {})
                                contexto_art = st.session_state.metadatos_articulos_editados.get(p_name, {}).get("contexto_unico", "").strip()
                                prompt_segmento, instruccion_segmento = unir_contextos(estrategia_contexto, contexto_art, contexto_dataset_manual)
                                with st.spinner(f"Mapeando relaciones para `{d_name}`..."):
                                    mapeo_relaciones_cruzadas(prompt_segmento, instruccion_segmento, df, d_name, p_name, idx, st)
                                    
                        else:
                            st.session_state.carpetas_destino[idx]["relaciones_cruzadas"].setdefault("Sin Artículo", {})
                            if not contexto_dataset_manual:
                                st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]["Sin Artículo"][d_name] = "No se proporcionó contexto manual ni artículo."
                            else:
                                with st.spinner(f"Analizando dataset `{d_name}`..."):
                                   relacion_dataset_contexto(contexto_dataset_manual, df, d_name, idx, st)
                    # Parte B: 🚀 Generación de Estrategia Altmetrics (Marketing Académico)
                    ctx_altmetrics_origen = ""
                    if pdfs_seleccionados:
                        ctx_altmetrics_origen = st.session_state.metadatos_articulos_editados.get(pdfs_seleccionados[0], {}).get("contexto_unico", "")
                    else:
                        ctx_altmetrics_origen = st.session_state.contextos_datasets.get(datasets_seleccionados[0], "")

                    with st.spinner("Generando Estrategia de Difusión Digital e Impacto Altmetrics..."):
                       generar_altmetrics(ctx_altmetrics_origen, idx, st)

            # Mostrar y editar las relaciones generadas en la UI
            if "relaciones_cruzadas" in st.session_state.carpetas_destino[idx] and st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]:
                st.markdown("### 📝 Relaciones del Dataset con el Contexto:")
                if pdfs_seleccionados:
                    for p_name in pdfs_seleccionados:
                        if p_name in st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]:
                            st.markdown(f"##### 📄 Artículo: `{p_name}`")
                            for d_name in datasets_seleccionados:
                                relacion_actual = st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name].get(d_name, "")
                                rel_editada = st.text_area(f"Relación de `{d_name}`:", value=relacion_actual, height=80, key=f"area_{idx}_{p_name}_{d_name}")
                                st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name][d_name] = rel_editada
                elif "Sin Artículo" in st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]:
                    st.markdown("##### 📊 Análisis basado en tu Contexto Escrito (Sin Artículo)")
                    for d_name in datasets_seleccionados:
                        relacion_actual = st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]["Sin Artículo"].get(d_name, "")
                        rel_editada = st.text_area(f"Relación analítica de `{d_name}`:", value=relacion_actual, height=80, key=f"area_solo_ds_{idx}_{d_name}")
                        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]["Sin Artículo"][d_name] = rel_editada

                # ⚡ PANELES VISUALES EN CUADROS INDEPENDIENTES (Alineados en Columnas en Paralelo)
                st.markdown("### 🚀 Estrategia de Difusión (Altmetrics Score Booster)")
                alt_data = st.session_state.carpetas_destino[idx].get("altmetrics", {})
                generar_ui_altmetrics(st, alt_data, idx)

    # 💾 PROCESO DE GUARDADO FÍSICO Y LÓGICA DEL JSON ESTRUCTURADO CON ALTMETRICS
    if st.button("💾 Guardar Todo de Forma Local", type="primary", use_container_width=True):
        guardar_json(datasets_dict, articulos_dict,st)           
        st.success("🎉 ¡Estructuras guardadas con éxito!")
        number_source = procesar_y_estructurar_indice()
        st.success(f"🎉 ¡Adicion al indice {number_source} elementos !")
        resumen_subida = upload_files_to_dataverse()
        st.info(f"Pipeline finalizado. Resumen: {resumen_subida}")