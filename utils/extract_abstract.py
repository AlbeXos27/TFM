import re
import pypdf

def extraer_zona_contexto_pdf(texto_completo):
    match = re.search(r'(abstract|resumen)(.*?)(1\.\s+introduction|1\.\s+introducción|2\.\s+|prolegómenos)', texto_completo, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0)[:6000]
    return texto_completo[:5000]

def extraer_contexto_pdf(archivo,articulos_dict,st):
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
        num_paginas_extraer = min(5, len(lector_pdf.pages))
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