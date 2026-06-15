def generar_ui_almetrics(st, alt_data, idx):
    col_fb, col_li, col_x = st.columns(3)

    with col_fb:
        with st.container(border=True):
            st.markdown("##### 👥 Facebook Impact")
            fb_editado = st.text_area(
                "Contenido para comunidades/muros:",
                value=alt_data.get("post_facebook", ""),
                height=200,
                key=f"fb_edit_{idx}",
            )
            st.session_state.carpetas_destino[idx]["altmetrics"][
                "post_facebook"
            ] = fb_editado

    with col_li:
        with st.container(border=True):
            st.markdown("##### 💼 LinkedIn Professional")
            li_editado = st.text_area(
                "Post largo de impacto científico:",
                value=alt_data.get("post_linkedin", ""),
                height=200,
                key=f"li_edit_{idx}",
            )
            st.session_state.carpetas_destino[idx]["altmetrics"][
                "post_linkedin"
            ] = li_editado

    with col_x:
        with st.container(border=True):
            st.markdown("##### 🐦 Twitter / X")
            tw_editado = st.text_area(
                "Hilado o tuit resumen (Max 280 car.):",
                value=alt_data.get("tweet_difusion", ""),
                height=200,
                key=f"tw_edit_{idx}",
            )
            st.session_state.carpetas_destino[idx]["altmetrics"][
                "tweet_difusion"
            ] = tw_editado
            st.caption(f"Caracteres: {len(tw_editado)} / 280")

    with st.container(border=True):
        st.markdown("##### 🎯 Comunidades Objetivo e Indexación Digital")
        tgt_editado = st.text_input(
            "Nichos de debate y entidades sugeridas:",
            value=alt_data.get("comunidad_objetivo", ""),
            key=f"tgt_edit_{idx}",
        )
        st.session_state.carpetas_destino[idx]["altmetrics"][
            "comunidad_objetivo"
        ] = tgt_editado