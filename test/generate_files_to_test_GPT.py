import os
import pandas as pd
import json
import fitz
from pathlib import Path
from openpyxl import load_workbook
from openai import OpenAI

# Inicializar el cliente de OpenAI (asegúrate de tener la variable de entorno OPENAI_API_KEY configurada)
client = OpenAI()

# Modelos equivalentes o recomendados en OpenAI
modelos = [
    "gpt-5.4-mini"
]

def evaluar_y_convertir_a_csv(ruta_excel: str) -> tuple[bool, str, pd.DataFrame | None]:
    """
    Determina si un Excel contiene una única tabla estructurada que pueda
    analizarse como un CSV.

    Retorna:
        (es_apto, motivo, dataframe)
    """
    ruta = Path(ruta_excel)

    if not ruta.exists():
        return False, f"No existe {ruta_excel}", None

    try:
        # ==========================================================
        # 1. Comprobar número de hojas
        # ==========================================================
        excel = pd.ExcelFile(ruta)

        if len(excel.sheet_names) != 1:
            return (
                False,
                f"El archivo tiene {len(excel.sheet_names)} hojas.",
                None,
            )

        hoja = excel.sheet_names[0]

        # ==========================================================
        # 2. Detectar celdas combinadas (mucho más fiable)
        # ==========================================================
        wb = load_workbook(ruta, read_only=False, data_only=True)
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
        df = pd.read_excel(
            ruta,
            sheet_name=hoja,
            header=None
        )

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
        datos = df.iloc[fila_cabecera + 1:].copy()
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
            nombre != "" and nombre.lower() != "nan"
            for nombre in datos.columns
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
            str(e),
            None,
        )


def obtener_max_tokens(num_columnas, tokens_por_campo=45, base=500):
    """Calcula el límite de tokens de salida necesario según las columnas."""
    estimacion = (num_columnas * tokens_por_campo) + base
    return min(max(1024, ((estimacion // 512) + 1) * 512), 8192)

def extraer_texto_optimizado(ruta_pdf, max_paginas = 8):
    doc = fitz.open(ruta_pdf)
    texto = ""
    
    paginas_a_leer = range(len(doc))
    if len(doc) > max_paginas:
        paginas_a_leer = list(range(6)) + list(range(len(doc)-2, len(doc)))

    for p in paginas_a_leer:
        texto += doc[p].get_text()
        
    return texto


articles = True
ruta_carpeta = "./datasets_with_article" if articles else "./datasets_no_article"

print("Iniciando pruebas con la API de OpenAI y formato JSON...\n")

for modelo in modelos:
    modelo_etiqueta = modelo.replace(":", "_")
    print(f"Cargando y probando: {modelo}...")

    ruta_guardar_archivos_test = Path(ruta_carpeta) / modelo_etiqueta / "files_from_test"
    ruta_guardar_archivos_test.mkdir(parents=True, exist_ok=True)
    
    prompt_sistema = (
        "Eres un experto científico de datos e investigador. Tu objetivo es explicar la estructura y los posibles usos de un dataset y deducir/extraer posibles autores, contenido. "
    )
    
    if not os.path.exists(ruta_carpeta):
        print(f"Error: La ruta '{ruta_carpeta}' no existe.")
        break

    archivos = [f for f in os.listdir(ruta_carpeta) if f.endswith(('.csv', '.xlsx', '.json', '.txt'))]
    
    if not archivos:
        print(f"No se encontraron archivos compatibles en {ruta_carpeta}")
        continue

    for nombre_archivo in archivos:
        ruta_completa = os.path.join(ruta_carpeta, nombre_archivo)
        tokens_maximos = 2000
        print(f"\n--> Analizando archivo: {nombre_archivo}")
        proposito_general = ""
        check = True
        
        try:
            if nombre_archivo.endswith('.csv'):
                df = pd.read_csv(ruta_completa, nrows=15, on_bad_lines='skip')
                columnas_y_tipos = str(df.dtypes.to_dict())
                muestra_datos = df.to_string()
                total_columnas = len(df.columns)
                tokens_maximos = obtener_max_tokens(total_columnas)
                        
            elif nombre_archivo.endswith(('.xlsx', '.xls')):
                check, motivo, df = evaluar_y_convertir_a_csv(ruta_completa)
                if not check:
                    print(f"⚠️ {nombre_archivo} no es apto para CSV: {motivo}")
                    muestra_datos = pd.read_excel(ruta_completa, nrows=60).to_string()
                    columnas_y_tipos = "Estructura realizada por humanos"
                else:
                    columnas_y_tipos = str(df.dtypes.to_dict())
                    muestra_datos = df.head(10).to_string()
                
            elif nombre_archivo.endswith('.json'):
                df = pd.read_json(ruta_completa, nrows=5)
                columnas_y_tipos = str(df.dtypes.to_dict())
                muestra_datos = df.to_string()
                
            elif nombre_archivo.endswith('.txt'):
                with open(ruta_completa, 'r', encoding='utf-8') as archivo_txt:
                    contenido = archivo_txt.read()
                columnas_y_tipos = "Archivo de texto plano"
                muestra_datos = contenido[:3000]
                
            else:
                continue
                
        except Exception as e:
            print(f"Error al procesar el archivo {nombre_archivo}: {e}")
            continue
        
        OPCIONES_SUBJECT = [
            "Natural Sciences",
            "Engineering and Technology",
            "Medical and Health Sciences",
            "Agricultural Sciences",
            "Social Sciences",
            "Humanities",
            "Other"  # Siempre es recomendable tener un valor comodín
        ]
        
        
        if check:
            prompt_usuario = f"""
            Analiza el archivo '{nombre_archivo}'.
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
                        "tipo_dato": "tipo (ej. int64, object, float64)",
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
                Analiza el archivo '{nombre_archivo}'.
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

        # Ejecución con la API de OpenAI
        try:
            response = client.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt_usuario}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )

            # Métricas simuladas/extraídas de la respuesta de OpenAI
            usage = response.usage
            tokens_generados = usage.completion_tokens if usage else 0
            
            # OpenAI no devuelve eval_duration de forma nativa, pero se puede estimar o dejar a 0 si no se requiere con precisión de milisegundos
            tiempo_inferencia = 0.0 
            tokens_por_segundo = 0.0
            
            contenido_respuesta = response.choices[0].message.content

            try:
                datos_json = json.loads(contenido_respuesta)
                datos_json["tokens_generados"] = tokens_generados
                datos_json["formato_tabla"] = check
                
                proposito_general = datos_json.get("proposito_general", "No se encontró el propósito general")
                
                with open(f"{ruta_guardar_archivos_test}/{nombre_archivo}.json", "w", encoding="utf-8") as f:
                    json.dump(datos_json, f, ensure_ascii=False, indent=4)
                        
            except json.JSONDecodeError:
                print(f"Error: La respuesta generada por {modelo} no es un JSON válido.")
                print(f"Contenido generado:\n{contenido_respuesta}")
                continue

        except Exception as e:
            print(f"Error en la inferencia con {modelo}: {e}")
            
        if articles:
            ruta_articulos = os.path.join(ruta_carpeta, "articles")

            if os.path.exists(ruta_articulos):
                articulos = [
                    f for f in os.listdir(ruta_articulos) 
                    if f.lower().endswith('.pdf')
                ]
            else:
                articulos = []
                print(f"⚠️ La carpeta {ruta_articulos} no existe.")
                
            if not articulos:
                print(f"No se encontraron artículos PDF en {ruta_carpeta}/articles")
                continue
            
            prefijo_dataset = nombre_archivo.split('.')[0]

            articulo_correspondiente = next(
                (art for art in articulos if art.split('.')[0] == prefijo_dataset), 
                None
            )
            
            if not articulo_correspondiente:
                continue

            ruta_pdf_completa = os.path.join(ruta_carpeta, "articles", articulo_correspondiente)
            print(f"--> Analizando artículo correspondiente: {articulo_correspondiente}")
            
            try:
                prompt_sistema_art = """Eres un experto en Bibliometría, Curación de Datos Científicos y Gestión de Repositorios de Investigación Abierta. Tu función es analizar textos académicos completos (artículos de investigación) y extraer metadatos estructurados para la caracterización y catalogación de los datos subyacentes.
Debes responder ÚNICAMENTE con un objeto JSON válido, estrictamente delimitado por las claves solicitadas, sin añadir introducciones, explicaciones ni bloques de texto adicionales fuera del JSON."""
                
                prompt_usuario_art = f"""
                Analiza el siguiente texto completo de un artículo científico:

                --- INICIO DEL ARTÍCULO ---
                {extraer_texto_optimizado(ruta_pdf_completa)}
                --- FIN DEL ARTÍCULO ---
                
                --- INICIO DEL DATASET ASOCIADO ---
                {proposito_general}
                --- FIN DEL DATASET ASOCIADO ---

                En cuanto a las keywords quiero que las extraigas de los articulos, no inventes palabras clave. Si no hay keywords explícitas, no escribas nada en el campo "keywords". 
                Si no hay DOI explícito, no escribas nada en el campo "doi".
                Con language, si el artículo está en español, pon "es", si está en inglés, pon "en". No inventes idiomas.

                Genera una respuesta UNICAMENTE en formato JSON válido con la siguiente estructura:
                {{
                    "title": "Título completo del artículo.",
                    "autores": ["Autor 1", "Autor 2", "..."],
                    "descripcion_dataset": "Para qué se ha usado el dataset con respecto al artículo.",
                    "subject": "Área de conocimiento.",
                    "keywords": ["palabra1", "palabra2", "..."],
                    "language": "es/en",
                    "resumen": "Resumen del artículo.",
                    "doi": "DOI del artículo si está disponible."
                }}
                """
                
                response_art = client.chat.completions.create(
                    model=modelo,
                    messages=[
                        {"role": "system", "content": prompt_sistema_art},
                        {"role": "user", "content": prompt_usuario_art}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2
                )
                
                contenido_art = response_art.choices[0].message.content
                usage_art = response_art.usage
                tokens_generados_art = usage_art.completion_tokens if usage_art else 0
                
                try:
                    datos_json_art = json.loads(contenido_art)
                    datos_json_art["tokens_generados"] = tokens_generados_art
                        
                    with open(f"{ruta_guardar_archivos_test}/{nombre_archivo}_articulo.json", "w", encoding="utf-8") as f:
                        json.dump(datos_json_art, f, ensure_ascii=False, indent=4)
                            
                except json.JSONDecodeError:
                    print(f"Error: La respuesta generada por {modelo} no es un JSON válido.")
                    print(f"Contenido generado:\n{contenido_art}")
                    continue
                
            except Exception as e:
                print(f"Error en la inferencia con {modelo}: {e}")

    print(f"Finalizado el procesamiento para {modelo}.\n" + "="*40 + "\n")