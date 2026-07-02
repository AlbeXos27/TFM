import json
import re
from groq import Groq
import streamlit as st
API_KEY_GROQ = st.secrets["API_KEY_GROQ"]
MODELO_LLM = st.secrets["MODELO_LLM"]

client = Groq(api_key=API_KEY_GROQ)

def generar_contexto_dataset (df,dataset_name,st):

    columnas_y_tipos = df.dtypes.to_string()
    muestra_datos = df.head(5).to_string()
    prompt_sistema = (
     "Eres un experto científico de datos e investigador. Tu objetivo es explicar la estructura, "
      "el propósito de un dataset y deducir/extraer posibles autores, investigadores o entidades creadoras basándote en sus metadatos o contenido. "
      "Asegúrate de escribir correctamente los nombres propios con sus tildes y eñes correspondientes en español."
    )
                
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
            temperature=0.2,
            response_format={ "type": "json_object" }
        )
        res_json = json.loads(respuesta.choices[0].message.content)
                    
        texto_analisis = f"{res_json.get('explicacion_campos')}"
        st.session_state.analisis_datasets[dataset_name] = texto_analisis
                    
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
        
        
def encontrar_autores_ia(texto_completo,datos_actuales,articulo_visualizar,st):
    
    pistas_metadatos = ", ".join(datos_actuales.get("autores_pdf_metadatos", []))
                    
    prompt_metadatos = f"""
                    Analiza la primera página y el contexto de este documento académico para mapear sus metadatos esenciales.
                    Necesito el título exacto del artículo, una lista limpia de los nombres propios de los autores y un resumen preciso de su marco científico.
                    
                    Pistas de autores recuperados de los metadatos del archivo: [{pistas_metadatos}]
                    
                    INSTRUCCIONES CRÍTICAS:
                    1. Revisa minuciosamente la primera página. Los nombres de los autores suelen estar juntos debajo del título.
                    2. Cruza el texto con las 'Pistas de autores'. Si los metadatos tienen nombres válidos, inclúyelos en el listado final.
                    3. Corrige activamente cualquier fallo de caracteres extraños, ligaduras de fuentes o tildes rotas que provengan de la extracción del PDF.
                    4. Si no consigues identificar autores en absoluto, deja el arreglo "autores_detectados" vacío: [].
                    
                    Responde ÚNICAMENTE con un objeto JSON estructurado con este formato exacto:
                    {{
                        "titulo": "Título completo del documento con tildes correctas",
                        "autores_detectados": ["Autor 1", "Autor 2", "Autor 3"],
                        "contexto_unico": "Resumen integrado del marco académico, objetivos e hipótesis del paper."
                    }}
                    
                    --- CONTEXTO DEL DOCUMENTO ---
                    {texto_completo[:5000]}
                    """
                    
    try:
        respuesta = client.chat.completions.create(
                            model=MODELO_LLM,
                            messages=[{"role": "user", "content": prompt_metadatos}],
                            response_format={"type": "json_object"},
                            temperature=0.1
        )
                        
        try:
            resultado = json.loads(respuesta.choices[0].message.content)
            if not isinstance(resultado, dict):
                resultado = {}
        except:
                resultado = {}
                        
        datos_actuales["titulo"] = resultado.get("titulo", articulo_visualizar)
        datos_actuales["contexto_unico"] = resultado.get("contexto_unico", "No se pudo generar el contexto automáticamente.")
                        
        autores_art_raw = resultado.get("autores_detectados", [])
        autores_art_filtrados = [
            a for a in autores_art_raw 
            if len(a) < 50 and "no se puede" not in a.lower() and "inferir" not in a.lower() and "desconocido" not in a.lower()
        ]
                        
        datos_actuales["autores_detectados"] = autores_art_filtrados
                        
                        # Combinamos metadatos limpios + IA evitando duplicados vacíos
        lista_inicial = list(set(datos_actuales["autores_pdf_metadatos"] + datos_actuales["autores_detectados"]))
        datos_actuales["autores_finales_seleccionados"] = [a for a in lista_inicial if a]
                        
        st.success("✅ Autores y contexto inicializados con IA")
        st.rerun() # Forzamos recarga para pintar los cambios inmediatamente en la UI
                        
    except Exception as e:
        datos_actuales["titulo"] = articulo_visualizar
        datos_actuales["contexto_unico"] = "No se pudo generar el contexto automáticamente."
        datos_actuales["autores_detectados"] = []
        datos_actuales["autores_finales_seleccionados"] = datos_actuales["autores_pdf_metadatos"].copy()
        st.error(f"Error al procesar con IA: {e}")
        
        
def mapeo_relaciones_cruzadas(prompt_segmento, instruccion_segmento, df, d_name, p_name, idx, st):
    prompt_relacion = f"""
    Actúa como un metodólogo científico y experto en analítica de datos. 
    {prompt_segmento}
    
    DATASET OBJETO DE ESTUDIO:
    - Nombre del archivo: '{d_name}'
    - Atributos / Columnas del archivo: {df.columns.tolist()}
    
    MISION DEL ANALISIS: {instruccion_segmento}
    
    REGLAS ESTRICTAS DE SALIDA:
    - Redacta una explicación fluida, analítica y estrictamente formal en español (máximo 4 líneas).
    """
    
    try:
        # Llamada a la API de OpenAI
        res_ia = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[{"role": "user", "content": prompt_relacion}],
            temperature=0.4
        )
        
        # Almacenamiento de la respuesta en el estado de Streamlit
        contenido_respuesta = res_ia.choices[0].message.content.strip()
        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name][d_name] = contenido_respuesta

    except Exception as e:
        # Control de errores
        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name][d_name] = f"Error: {e}"
                
def relacion_dataset_contexto(contexto_dataset_manual, df, d_name, idx, st):
    # Definición del prompt para el LLM
    prompt_relacion_solo_ds = f"""
    CONTEXTO ESPECÍFICO DEL DATASET: "{contexto_dataset_manual}"
    Estructura del archivo '{d_name}': {df.columns.tolist()}
    
    Genera una explicación analítica y formal en español (máximo 4 líneas) sobre cómo los datos se aplican al contexto.
    """
    
    try:
        # Llamada a la API de OpenAI
        res_ia = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[{"role": "user", "content": prompt_relacion_solo_ds}],
            temperature=0.3
        )
        
        # Extracción y guardado del resultado en el estado de Streamlit
        respuesta_texto = res_ia.choices[0].message.content.strip()
        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]["Sin Artículo"][d_name] = respuesta_texto
        
    except Exception as e:
        # Control de excepciones
        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]["Sin Artículo"][d_name] = f"Error: {e}"
        
def generar_altmetrics(ctx_altmetrics_origen, idx, st):
    # Definición del prompt estructurado para salida JSON
    prompt_altmetrics = f"""
    Eres un experto en comunicación de la ciencia y métricas alternativas (Altmetrics).
    Tu objetivo es redactar contenido para maximizar el impacto social y digital del siguiente marco de investigación:
    "{ctx_altmetrics_origen}"
    
    Genera obligatoriamente un formato JSON válido y estricto con los siguientes campos:
    {{
        "post_facebook": "Un post divulgativo largo adaptado al tono dinámico de Facebook, cercano pero riguroso, ideal para compartir en páginas de debate o grupos de investigación.",
        "tweet_difusion": "Un tweet de divulgación científica riguroso, que llame a la acción, use hashtags académicos y mida menos de 260 caracteres.",
        "post_linkedin": "Un artículo profesional corto de 2 párrafos enfocado en el impacto, beneficios metodológicos y alcances del proyecto.",
        "comunidad_objetivo": "Lista separada por comas de instituciones, ONGs, entidades públicas o foros donde este dataset y paper deben ser discutidos."
    }}
    Responde en español y cuida perfectamente las tildes.
    """

    try:
        # Llamada a la API forzando el modo JSON
        res_alt = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[{"role": "user", "content": prompt_altmetrics}],
            response_format={"type": "json_object"},
            temperature=0.35,
        )

        # Parseo y almacenamiento del JSON en el estado de Streamlit
        contenido_json = res_alt.choices[0].message.content
        st.session_state.carpetas_destino[idx]["altmetrics"] = json.loads(
            contenido_json
        )

    except Exception as e:
        # Estructura fallback con mensajes de error en caso de fallo
        st.session_state.carpetas_destino[idx]["altmetrics"] = {
            "post_facebook": "Error al generar post automático de Facebook.",
            "tweet_difusion": "Error al generar tuit automático.",
            "post_linkedin": "Error al generar post automático.",
            "comunidad_objetivo": f"Error al procesar objetivos: {e}",
        }


def extraer_subjects(contexto, nombre_archivo):
    """
    Extrae las áreas temáticas principales (subjects) del contexto usando Groq.
    Devuelve una lista de subjects válidos para la API de Dataverse.
    
    Args:
        contexto (str): El texto/descripción del documento o dataset
        nombre_archivo (str): Nombre del archivo para referencia
    
    Returns:
        list: Lista de subjects en inglés compatibles con Dataverse (máximo 5)
    """
    prompt_subjects = f"""Analiza el siguiente contexto de investigación y extrae exactamente 3 a 5 áreas temáticas principales.
    
CONTEXTO: "{contexto}"

Devuelve ÚNICAMENTE un JSON con este formato, sin explicaciones adicionales:
{{
    "subjects": ["Tema 1", "Tema 2", "Tema 3"]
}}

Los temas pueden estar en español o en inglés. Al final, asigna los subjects a valores compatibles con Dataverse como:
"Agricultural Sciences", "Arts and Humanities", "Astronomy and Astrophysics", "Business and Management", "Chemistry", "Computer and Information Science", "Earth and Environmental Sciences", "Engineering", "Law", "Mathematical Sciences", "Medicine, Health and Life Sciences", "Physics", "Social Sciences", "Other".
"""
    
    def normalize_text(value):
        # Asegura la eliminación de comas para normalizaciones complejas
        return re.sub(r"[^a-z0-9]+", " ", value.lower().strip()) if isinstance(value, str) else ""

    def map_subject(value):
        if not isinstance(value, str):
            return None
        
        normalized = normalize_text(value)
        
        # 1. Diccionario completo con mapeos en español e inglés normalizado
        mapping = {
            # Mapeos de traducción del Español
            "salud": "Medicine, Health and Life Sciences",
            "medicina": "Medicine, Health and Life Sciences",
            "ciencias de la vida": "Medicine, Health and Life Sciences",
            "vida": "Medicine, Health and Life Sciences",
            "ciencias sociales": "Social Sciences",
            "ciencias de la tierra": "Earth and Environmental Sciences",
            "ciencias de la tierra y el medio ambiente": "Earth and Environmental Sciences",
            "tecnologia": "Computer and Information Science",
            "tecnología": "Computer and Information Science",
            "informatica": "Computer and Information Science",
            "informática": "Computer and Information Science",
            "ciencias de la computacion": "Computer and Information Science",
            "ciencias de la computación": "Computer and Information Science",
            "fisica": "Physics",
            "física": "Physics",
            "quimica": "Chemistry",
            "química": "Chemistry",
            "ingenieria": "Engineering",
            "ingeniería": "Engineering",
            "ley": "Law",
            "derecho": "Law",
            "artes": "Arts and Humanities",
            "humanidades": "Arts and Humanities",
            "matematicas": "Mathematical Sciences",
            "matemáticas": "Mathematical Sciences",
            "agricultura": "Agricultural Sciences",
            "negocios": "Business and Management",
            "empresa": "Business and Management",

            # 2. Mapeos estrictos en inglés (para corregir variaciones que devuelva la IA)
            "agricultural sciences": "Agricultural Sciences",
            "arts and humanities": "Arts and Humanities",
            "astronomy and astrophysics": "Astronomy and Astrophysics",
            "business and management": "Business and Management",
            "chemistry": "Chemistry",
            "computer and information science": "Computer and Information Science",
            "earth and environmental sciences": "Earth and Environmental Sciences",
            "engineering": "Engineering",
            "law": "Law",
            "mathematical sciences": "Mathematical Sciences",
            "medicine health and life sciences": "Medicine, Health and Life Sciences",
            "medicine health & life sciences": "Medicine, Health and Life Sciences",
            "physics": "Physics",
            "social sciences": "Social Sciences",
            "other": "Other"
        }
        
        # Retorna el string exacto si existe en el diccionario, de lo contrario None
        return mapping.get(normalized, None)

    try:
        respuesta = client.chat.completions.create(
            model=MODELO_LLM,
            messages=[{"role": "user", "content": prompt_subjects}],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        resultado = json.loads(respuesta.choices[0].message.content)
        subjects_extraidos = resultado.get("subjects", [])
        
        subjects_mapeados = []
        for raw in subjects_extraidos:
            mapped = map_subject(raw)
            if mapped and mapped not in subjects_mapeados:
                subjects_mapeados.append(mapped)
            if len(subjects_mapeados) >= 5:
                break

        if subjects_mapeados:
            return subjects_mapeados
        return ["Social Sciences"]
            
    except Exception as e:
        print(f"⚠️ Error al extraer subjects: {e}")
        return ["Social Sciences"]  # Default fallback