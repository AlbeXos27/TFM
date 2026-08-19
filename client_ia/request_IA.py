import streamlit as st
import pandas as pd
import ollama
import fitz
from pathlib import Path
import pandas as pd
from pathlib import Path
from openpyxl import load_workbook
import json
from typing import Union, Tuple, Optional
import io


def evaluar_y_convertir_a_csv(
    origen_excel: Union[str, Path, io.BytesIO],
) -> Tuple[bool, str, Optional[pd.DataFrame]]:
    """
    Determina si un Excel contiene una única tabla estructurada que pueda
    analizarse como un CSV. Acepta tanto rutas en disco (str/Path)
    como objetos de archivo en memoria (UploadedFile / BytesIO de Streamlit).

    Retorna:
        (es_apto, motivo, dataframe)
    """

    try:
        # ==========================================================
        # 0. Validar origen y gestionar punteros de memoria
        # ==========================================================
        if isinstance(origen_excel, (str, Path)):
            ruta = Path(origen_excel)
            if not ruta.exists():
                return False, f"No existe {origen_excel}", None
            target = ruta
        else:
            # Es un UploadedFile o BytesIO
            target = origen_excel
            if hasattr(target, "seek"):
                target.seek(0)

        # ==========================================================
        # 1. Comprobar número de hojas
        # ==========================================================
        excel = pd.ExcelFile(target)

        if len(excel.sheet_names) != 1:
            return (
                False,
                f"El archivo tiene {len(excel.sheet_names)} hojas.",
                None,
            )

        hoja = excel.sheet_names[0]

        # ==========================================================
        # 2. Detectar celdas combinadas (openpyxl)
        # ==========================================================
        if hasattr(target, "seek"):
            target.seek(0)  # Rebobinar antes de pasarlo a openpyxl

        wb = load_workbook(target, read_only=False, data_only=True)
        ws = wb[hoja]

        if ws.merged_cells.ranges:
            return (
                False,
                "Contiene celdas combinadas.",
                None,
            )

        # ==========================================================
        # 3. Leer todo sin cabecera
        # ==========================================================
        if hasattr(target, "seek"):
            target.seek(0)  # Rebobinar antes de pasarlo a pandas

        df = pd.read_excel(target, sheet_name=hoja, header=None)

        df = df.dropna(how="all").dropna(axis=1, how="all")

        if df.empty:
            return False, "El Excel está vacío.", None

        # ==========================================================
        # 4. Buscar automáticamente la cabecera
        # ==========================================================
        fila_cabecera = None

        for i, fila in df.iterrows():
            ocupacion = fila.notna().mean()
            if ocupacion >= 0.80:
                fila_cabecera = i
                break

        if fila_cabecera is None:
            return (
                False,
                "No se encontró una cabecera clara.",
                None,
            )

        # ==========================================================
        # 5. Reconstruir tabla
        # ==========================================================
        cabecera = df.iloc[fila_cabecera].astype(str).str.strip()
        datos = df.iloc[fila_cabecera + 1 :].copy()
        datos.columns = cabecera

        datos = datos.dropna(axis=1, how="all")
        datos = datos.dropna(how="all")

        if datos.empty:
            return (
                False,
                "No hay filas de datos tras la cabecera.",
                None,
            )

        # ==========================================================
        # 6. Validar cabecera
        # ==========================================================
        nombres_validos = sum(
            nombre != "" and nombre.lower() != "nan" for nombre in datos.columns
        )

        if nombres_validos / len(datos.columns) < 0.8:
            return (
                False,
                "La cabecera parece inválida.",
                None,
            )

        # ==========================================================
        # 7. Comprobar homogeneidad de las filas
        # ==========================================================
        ocupacion_filas = datos.notna().mean(axis=1)

        if ocupacion_filas.mean() < 0.60:
            return (
                False,
                "La estructura del dataset es demasiado irregular.",
                None,
            )

        return (
            True,
            "Tabla estructurada correctamente.",
            datos.reset_index(drop=True),
        )

    except Exception as e:
        return (
            False,
            f"Error al evaluar Excel: {str(e)}",
            None,
        )


def obtener_max_tokens(num_columnas, tokens_por_campo=45, base=500):
    """Calcula el límite de tokens de salida necesario según las columnas."""
    estimacion = (num_columnas * tokens_por_campo) + base
    # Redondeamos hacia arriba en bloques de 512 tokens
    return min(
        max(1024, ((estimacion // 512) + 1) * 512), 16384
    )  # Limite máximo de 16k tokens


def carga_modelo(modelo):
    try:
        ollama.chat(
            model=modelo,
            messages=[{"role": "user", "content": "test"}],
            options={"temperature": 0.1},
            think=False,
        )
        return True
    except Exception as e:
        print(f"Aviso en warm-up para {modelo}: {e}")


def generar_contexto_dataset(df, dataset_name, st):
    config = {}
    try:
        with open("./config.json", "r", encoding="utf-8") as archivo:
            config = json.load(archivo)
    except Exception as e:
        print(f"No se pudo cargar el archivo de configuración: {e}")

    # Inicializamos variables por seguridad
    columnas_y_tipos = ""
    muestra_datos = ""
    evaluar = True  # Valor por defecto
    tokens_maximos = 2000  # Valor por defecto

    try:

        if dataset_name.endswith(".csv"):
            df_leido = pd.read_csv(df, nrows=20, on_bad_lines="skip")
            columnas_y_tipos = str(df_leido.dtypes.to_dict())
            muestra_datos = df_leido.to_string()
            total_columnas = len(df_leido.columns)
            tokens_maximos = obtener_max_tokens(total_columnas)

        elif dataset_name.endswith((".xlsx", ".xls")):

            evaluar, motivo, df_evaluado = evaluar_y_convertir_a_csv(df)
            if not evaluar:

                if hasattr(df, "seek"):
                    df.seek(0)
                    muestra_datos = pd.read_excel(df, nrows=60).to_string()
                    columnas_y_tipos = "Estructura realizada por humanos"
            else:
                columnas_y_tipos = str(df_evaluado.dtypes.to_dict())
                muestra_datos = df_evaluado.head(10).to_string()

        elif dataset_name.endswith(".json"):
            df_leido = pd.read_json(df, nrows=5)
            columnas_y_tipos = str(df_leido.dtypes.to_dict())
            muestra_datos = df_leido.to_string()

        elif dataset_name.endswith(".txt"):
            contenido_bytes = df.read()
            if isinstance(contenido_bytes, bytes):
                contenido = contenido_bytes.decode("utf-8", errors="ignore")
            else:
                contenido = contenido_bytes
            columnas_y_tipos = "Archivo de texto plano"
            muestra_datos = contenido[:3000]

    except Exception as e:
        print(f"Error al procesar el archivo {dataset_name}: {e}")
        return None

    OPCIONES_SUBJECT = [
        "Natural Sciences",
        "Engineering and Technology",
        "Medical and Health Sciences",
        "Agricultural Sciences",
        "Social Sciences",
        "Humanities",
        "Other",
    ]

    if evaluar:
        prompt_usuario = f"""
            Analiza el archivo '{dataset_name}'.
            Columnas y tipos de datos:
            {columnas_y_tipos}
            Muestra de las primeras filas:
            {muestra_datos}
                                
            Genera una respuesta UNICAMENTE en formato JSON válido con la siguiente estructura.        
            Para la "explicacion_campos", devuelve una lista de diccionarios, donde cada uno detalle claramente el campo, su tipo de dato y su respectiva explicación.
            Para los posibles_uso que sea facil de parsear, solo escribe los valores con coma sigue el ejemplo ESTRICTAMENTE.
            Elige OBLIGATORIAMENTE uno y solo uno de los siguientes valores exactos para el subject: {', '.join(OPCIONES_SUBJECT)}. Si no estás seguro, asigna 'Other'.                                
            {{
                "proposito_general": "Breve explicación de para qué sirve este archivo.",
                "explicacion_campos": [
                    {{
                        "campo": "nombre_de_la_columna",
                        "tipo_dato": "tipo (ej. int64, str, float64)",
                        "explicacion": "Explicación detallada de lo que representa este campo."
                    }}
                ],
                "posibles_uso": ["uso1", "uso2", "..."],
                "palabras_clave": ["palabra_clave1", "palabra_clave2", "..."],
                "subject": "Tema o área de conocimiento relacionada con este campo."
            }}
            """
    else:
        prompt_usuario = f"""
            Analiza el archivo '{dataset_name}'.
            Columnas y tipos de datos:
            {columnas_y_tipos}
            Muestra de las primeras filas:
            {muestra_datos}
                                    
            Genera una respuesta UNICAMENTE en formato JSON válido con la siguiente estructura.
            Para los posibles_uso que sea facil de parsear, solo escribe los valores con coma sigue el ejemplo ESTRICTAMENTE.
            Elige OBLIGATORIAMENTE uno y solo uno de los siguientes valores exactos para el subject: {', '.join(OPCIONES_SUBJECT)}. Si no estás seguro, asigna 'Other'.                                
                                 
            {{
                "proposito_general": "Breve explicación de para qué sirve este archivo.",
                "explicacion_campos": "Explicación general de la estructura del dataset, sin inventar campos ni tipos de datos.",
                "posibles_uso": ["uso1", "uso2", "..."],
                "palabras_clave": ["palabra_clave1", "palabra_clave2", "..."],
                "subject": "Tema o área de conocimiento relacionada con este campo."
            }}
            """
    try:

        response = ollama.chat(
            model=config["modelo_dataset"],
            messages=[
                {"role": "system", "content": config["prompt_sistema_dataset"]},
                {"role": "user", "content": prompt_usuario},
            ],
            format="json",
            options={"temperature": 0.1, "max_tokens": tokens_maximos},
            think=False,
        )

        try:

            st.session_state.analisis_datasets[dataset_name] = json.loads(
                response["message"]["content"]
            )

        except json.JSONDecodeError:
            print(
                f"Error: La respuesta generada por {config['modelo_dataset']} no es un JSON válido."
            )
            print(f"Contenido generado:\n{response['message']['content']}")

    except Exception as e:
        print(f"Error en la inferencia con {config['modelo_dataset']}: {e}")

    if dataset_name not in st.session_state.metadatos_datasets_editados:
        st.session_state.metadatos_datasets_editados[dataset_name] = {
            "titulo": dataset_name,
            "autores_detectados": [],
            "autores_finales_seleccionados": [],
            "orcids_vinculados": {},
            "resultados_busqueda_api": {},
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
    OPCIONES_DATAVERSE = [
        "Agricultural Sciences", "Arts and Humanities", "Astronomy and Astrophysics",
        "Business and Management", "Chemistry", "Computer and Information Science",
        "Earth and Environmental Sciences", "Engineering", "Law", "Mathematical Sciences",
        "Medicine, Health and Life Sciences", "Physics", "Social Sciences", "Other",
    ]

    prompt_subjects = f"""Analiza el siguiente contexto de investigación y clasifícalo en 1 a 3 de las siguientes áreas temáticas de Dataverse.

CONTEXTO: "{contexto}"

VALORES PERMITIDOS (elige ÚNICAMENTE entre estos, copiándolos EXACTAMENTE tal cual, sin traducir ni modificar):
{', '.join(OPCIONES_DATAVERSE)}

Devuelve ÚNICAMENTE un JSON con este formato, sin explicaciones adicionales y sin inventar valores nuevos:
{{
    "subjects": ["Valor permitido 1", "Valor permitido 2"]
}}
"""

    response = ollama.chat(
        model="qwen3.5:4b",
        messages=[{"role": "user", "content": prompt_subjects}],
        format="json",
        options={"temperature": 0.2, "max_tokens": 512},
        think=False,
    )

    try:
        contenido = json.loads(response["message"]["content"])
    except json.JSONDecodeError as e:
        print(f"Error: la respuesta de extraer_subjects no es un JSON válido: {e}")
        return ["Other"]

    subjects_crudos = contenido.get("subjects", []) if isinstance(contenido, dict) else []

    opciones_por_lower = {op.lower(): op for op in OPCIONES_DATAVERSE}
    subjects_validos = []
    for subject in subjects_crudos:
        if not isinstance(subject, str):
            continue
        subject_normalizado = opciones_por_lower.get(subject.strip().lower())
        if subject_normalizado and subject_normalizado not in subjects_validos:
            subjects_validos.append(subject_normalizado)

    return subjects_validos if subjects_validos else ["Other"]
    
    


def extraer_metadatos_articles(st, articulo_name, articulo):
    """
    Extrae metadatos de los artículos PDF cargados usando Groq.
    Actualiza st.session_state.metadatos_articulos_editados con los resultados.

    Args:
        st: Streamlit session
        articulo_name (str): Nombre del artículo
        articulo (Any): Objeto del artículo
    """
    
    config = {}
    try:
        with open("./config.json", "r", encoding="utf-8") as archivo:
            config = json.load(archivo)
    except Exception as e:
        print(f"No se pudo cargar el archivo de configuración: {e}")

    prompt_sistema = config.get("prompt_sistema_articulos", "Eres un experto en análisis de artículos científicos.")
    prompt_usuario = f"""
        Analiza el siguiente texto completo de un artículo científico:
    
        --- INICIO DEL ARTÍCULO ---
        {articulo}
        --- FIN DEL ARTÍCULO ---
                                    
        En cuanto a las keywords quiero que las extraigas de los articulos, no inventes palabras clave. Si no hay keywords explícitas, no escribas nada en el campo "keywords". 
        Si no hay DOI explícito, no escribas nada en el campo "doi".
        Con language, si el artículo está en español, pon "es", si está en inglés, pon "en". No inventes idiomas.
        El resumen del articulo debe estar en español, si el artículo está en inglés, tradúcelo al español. No inventes resúmenes.
        
        Genera una respuesta UNICAMENTE en formato JSON válido con la siguiente estructura:
        {{
        "title": "Título completo del artículo.",
        "autores": ["Autor 1", "Autor 2", "..."],
        "subject": "Área de conocimiento principal del artículo.",
        "keywords": ["palabra1", "palabra2", "..."],
        "language": "es/en",
        "resumen": "Resumen del artículo.",
        "doi": "DOI del artículo si está disponible."
    }}
    """
    try:
        response = ollama.chat(
        model="qwen3.5:4b",
        messages=[
            {"role": "system", "content": prompt_sistema},
            {"role": "user", "content": prompt_usuario}
        ],
        format='json',
        options={'temperature': 0.2},
        think = False
        )
        return response["message"]["content"]
    except Exception as e:
        print(f"Error en la inferencia de metadatos para {articulo_name}: {e}")
        return json.dumps({
            "title": articulo_name,
            "autores": [],
            "subject": "",
            "keywords": [],
            "language": "es",
            "resumen": f"Error: {e}",
            "doi": ""
        })
        
def mapeo_relaciones_cruzadas(prompt_segmento, instruccion_segmento, df, d_name, p_name, idx, st):
    prompt_relacion = f"""
    Actúa como un metodólogo científico y experto en analítica de datos. 
    {prompt_segmento}
    
    DATASET OBJETO DE ESTUDIO:
    - Nombre del archivo: '{d_name}'
    - Atributos / Columnas del archivo: {st.session_state.analisis_datasets.get(d_name, {}).get('explicacion_campos', 'No disponible')}
    
    MISION DEL ANALISIS: {instruccion_segmento}
    
    REGLAS ESTRICTAS DE SALIDA:
    - Redacta una explicación fluida, analítica y estrictamente formal en español (máximo 4 líneas).
    """
    
    try:
        # Llamada a la API de OpenAI
        response = ollama.chat(
            model="qwen3.5:4b",
            messages=[{"role": "user", "content": prompt_relacion}],
            options={'temperature': 0.2},
            think = False
        )
        
        # Almacenamiento de la respuesta en el estado de Streamlit
        contenido_respuesta = response["message"]["content"]
        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name][d_name] = contenido_respuesta

    except Exception as e:
        # Control de errores
        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"][p_name][d_name] = f"Error: {e}"
                
def relacion_dataset_contexto(contexto_dataset_manual, df, d_name, idx, st):
    # Definición del prompt para el LLM
    prompt_relacion_solo_ds = f"""
    CONTEXTO ESPECÍFICO DEL DATASET: "{contexto_dataset_manual}"
    Estructura del archivo '{d_name}': {st.session_state.analisis_datasets.get(d_name, {}).get('explicacion_campos', 'No disponible')}
    
    Genera una explicación analítica y formal en español (máximo 4 líneas) sobre cómo los datos se aplican al contexto.
    """
    
    try:
        # Llamada a la API de OpenAI
        response = ollama.chat(
            model="qwen3.5:4b",
            messages=[{"role": "user", "content": prompt_relacion_solo_ds}],
            options={'temperature': 0.2},
            think = False
        )
        
        # Extracción y guardado del resultado en el estado de Streamlit
        respuesta_texto = response["message"]["content"]
        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]["Sin Artículo"][d_name] = respuesta_texto
        
    except Exception as e:
        # Control de excepciones
        st.session_state.carpetas_destino[idx]["relaciones_cruzadas"]["Sin Artículo"][d_name] = f"Error: {e}"