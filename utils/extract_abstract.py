import re
import pypdf

def extraer_zona_contexto_pdf(texto_completo):
    match = re.search(r'(abstract|resumen)(.*?)(1\.\s+introduction|1\.\s+introducción|2\.\s+|prolegómenos)', texto_completo, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0)[:6000]
    return texto_completo[:5000]

import re


def extraer_contexto_pdf(archivo, articulos_dict, st):
    try:
        archivo.seek(0)
        lector_pdf = pypdf.PdfReader(archivo)
        archivo.seek(0)
        pdf_bytes = archivo.read()

        autores_metadatos = []
        keywords_metadatos = []

        # 1. Extracción de metadatos del PDF (Autores y Keywords)
        if lector_pdf.metadata:
            # --- Extracción de Autores ---
            if lector_pdf.metadata.author:
                autor_raw = lector_pdf.metadata.author.strip()
                if autor_raw:
                    autor_limpio = autor_raw.replace(";", ",")
                    autor_limpio = re.sub(
                        r"\s+(?:and|y|&|-)\s+", ", ", autor_limpio, flags=re.IGNORECASE
                    )
                    autores = [
                        a.strip() for a in autor_limpio.split(",") if a.strip()
                    ]
                    autores_metadatos = autores if autores else [autor_raw]

            # --- Extracción de Keywords ---
            if lector_pdf.metadata.keywords:
                keywords_raw = lector_pdf.metadata.keywords.strip()
                if keywords_raw:
                    keywords_limpias = keywords_raw.replace(";", ",")
                    keywords_limpias = re.sub(
                        r"\s+(?:and|y|&|-)\s+", ", ", keywords_limpias, flags=re.IGNORECASE
                    )
                    keywords = [
                        kw.strip() for kw in keywords_limpias.split(",") if kw.strip()
                    ]
                    keywords_metadatos = keywords if keywords else [keywords_raw]

        # 2. Extracción de texto de las primeras páginas
        texto_pdf = ""
        num_paginas_extraer = min(5, len(lector_pdf.pages))
        for i in range(num_paginas_extraer):
            try:
                texto_extraido = lector_pdf.pages[i].extract_text()
                if texto_extraido:
                    texto_pdf += f"\n--- Página {i+1} ---\n{texto_extraido}"
                else:
                    texto_pdf += f"\n[Página {i+1} sin texto o es imagen]\n"
            except Exception:
                texto_pdf += (
                    f"\n[No se pudo extraer texto de la página {i+1}]\n"
                )

        # 3. Guardado en estado
        st.session_state.textos_articulos[archivo.name] = texto_pdf
        articulos_dict[archivo.name] = pdf_bytes

        if archivo.name not in st.session_state.metadatos_articulos_editados:
            st.session_state.metadatos_articulos_editados[archivo.name] = {
                "autores_pdf_metadatos": autores_metadatos,
                "keywords_pdf_metadatos": keywords_metadatos,
                "autores_detectados": [],
                "autores_finales_seleccionados": [],
                "orcids_vinculados": {},
                "resultados_busqueda_api": {},
                "keywords_finales_seleccionadas": [],
            }
        else:
            st.session_state.metadatos_articulos_editados[archivo.name][
                "autores_pdf_metadatos"
            ] = autores_metadatos
            st.session_state.metadatos_articulos_editados[archivo.name][
                "keywords_pdf_metadatos"
            ] = keywords_metadatos

    except Exception as e:
        st.error(f"No se pudo leer el PDF {archivo.name}: {e}")