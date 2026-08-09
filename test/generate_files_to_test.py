import os
import pandas as pd
import ollama
import json
import fitz
from pathlib import Path
import pandas as pd
from pathlib import Path
from openpyxl import load_workbook

modelos = [
    "llama3.2:3b",
    "qwen3.5:4b",
    "granite4.1:3b"
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
    # Redondeamos hacia arriba en bloques de 512 tokens
    return min(max(1024, ((estimacion // 512) + 1) * 512), 8192)  # Limite superior de 12k tokens

def extraer_texto_optimizado(ruta_pdf, max_paginas = 8):
    doc = fitz.open(ruta_pdf)
    texto = ""
    
    # Si tiene más de 12 páginas, leemos las primeras 10 (Título, Autores, Intro, Metodología/Data)
    # y las últimas 2 (Conclusiones), saltándonos la bibliografía pesada del final.
    paginas_a_leer = range(len(doc))
    if len(doc) > max_paginas:
        # Leemos primeras 6 páginas + últimas 2 páginas (por si el dataset se describe al final)
        paginas_a_leer = list(range(6)) + list(range(len(doc)-2, len(doc)))

    for p in paginas_a_leer:
        texto += doc[p].get_text()
        
    return texto


articles = False

ruta_carpeta = "./datasets_with_article" if articles else "./datasets_no_article"


print("Iniciando pruebas de inferencia pura con limpieza de VRAM y formato personalizado...\n")

for modelo in modelos:
    modelo_etiqueta = modelo.replace(":", "_")
    print(f"Cargando y probando: {modelo}...")

    # 1. Definimos la ruta usando Path (puedes usar el operador '/' de pathlib)
    ruta_guardar_archivos_test = Path(ruta_carpeta) / modelo_etiqueta / "files_from_test"
    
    # 2. Creamos la carpeta
    ruta_guardar_archivos_test.mkdir(parents=True, exist_ok=True)

    # 1. Warm-up (Calentamiento): Sube el modelo a la VRAM para no medir la carga
    try:
        ollama.chat(
            model=modelo,
            messages=[{'role': 'user', 'content': 'test'}],
            options={'temperature': 0.1},
            think = False
        )
    except Exception as e:
        print(f"Aviso en warm-up para {modelo}: {e}")
    
    prompt_sistema = (
        "Eres un experto científico de datos e investigador. Tu objetivo es explicar la estructura y los posibles usos de un dataset y deducir/extraer posibles autores, contenido. "
    )
    
    # Verificamos que la carpeta exista
    if not os.path.exists(ruta_carpeta):
        print(f"Error: La ruta '{ruta_carpeta}' no existe.")
        break

    # Recorremos todos los archivos de la carpeta
    archivos = [f for f in os.listdir(ruta_carpeta) if f.endswith(('.csv', '.xlsx', '.json', '.txt'))]
    
    if not archivos:
        print(f"No se encontraron archivos compatibles en {ruta_carpeta}")
        continue

    for nombre_archivo in archivos:
        ruta_completa = os.path.join(ruta_carpeta, nombre_archivo)
        tokens_maximos = 2000  # Valor por defecto, se ajustará según el dataset
        print(f"\n--> Analizando archivo: {nombre_archivo}")
        proposito_general = ""
        check = True  # Variable para controlar si el archivo es apto para CSV
        
        # Intentamos leer el dataset o archivo según su tipo
        try:
            if nombre_archivo.endswith('.csv'):
                df = pd.read_csv(ruta_completa, nrows=15,on_bad_lines='skip')
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
                # Si es un texto plano, leemos el contenido directamente
                with open(ruta_completa, 'r', encoding='utf-8') as archivo_txt:
                    contenido = archivo_txt.read()
                columnas_y_tipos = "Archivo de texto plano"
                muestra_datos = contenido[:3000] # Primeros 3000 caracteres como muestra
                
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
            "Other" 
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

        # 2. Ejecución real de la prueba que vamos a medir
        try:
            response = ollama.chat(
                model=modelo,
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt_usuario}
                ],
                format='json',
                options={'temperature': 0.1, 'max_tokens': tokens_maximos},
                think = False
            )

            # Extraemos métricas puras de inferencia
            tiempo_inferencia = response.get('eval_duration', 0) / 1e9
            tokens_generados = response.get('eval_count', 0)
            tokens_por_segundo = tokens_generados / tiempo_inferencia if tiempo_inferencia > 0 else 0
            
            try:
                
                datos_json = json.loads(response['message']['content'])
                datos_json["tiempo_inferencia"] = f"{tiempo_inferencia:.2f}"
                datos_json["tokens_generados"] = tokens_generados
                datos_json["tokens_por_segundo"] = f"{tokens_por_segundo:.2f}"
                datos_json["formato_tabla"] = check
                
                proposito_general = datos_json.get("proposito_general", "No se encontró el propósito general")
                
                with open(f"{ruta_guardar_archivos_test}/{nombre_archivo}.json", "w", encoding="utf-8") as f:
                    json.dump(datos_json, f, ensure_ascii=False, indent=4)
                           
            except json.JSONDecodeError:
                print(f"Error: La respuesta generada por {modelo} no es un JSON válido.")
                print(f"Contenido generado:\n{response['message']['content']}")
                continue


        except Exception as e:
            print(f"Error en la inferencia con {modelo}: {e}")
            
            
        if articles:
            
            ruta_articulos = os.path.join(ruta_carpeta, "articles")

            # Comprobamos que la carpeta exista antes de listar para evitar FileNotFoundError
            if os.path.exists(ruta_articulos):
                articulos = [
                    f for f in os.listdir(ruta_articulos) 
                    if f.lower().endswith('.pdf')  # lower() evita ignorar archivos con extensión .PDF
                ]
            else:
                articulos = []
                print(f"⚠️ La carpeta {ruta_articulos} no existe.")
                
            if not articulos:
                print(f"No se encontraron artículos PDF en {ruta_carpeta}/articles")
                continue
            
            prefijo_dataset = nombre_archivo.split('.')[0]

            # Buscamos el artículo cuyo prefijo coincida
            articulo_correspondiente = next(
                (art for art in articulos if art.split('.')[0] == prefijo_dataset), 
                None
            )
            ruta_pdf_completa = os.path.join(ruta_carpeta, "articles", articulo_correspondiente)
            
            print(f"--> Analizando artículo correspondiente: {articulo_correspondiente}")
            
            try:
                
                        prompt_sistema = """Eres un experto en Bibliometría, Curación de Datos Científicos y Gestión de Repositorios de Investigación Abierta. Tu función es analizar textos académicos completos (artículos de investigación) y extraer metadatos estructurados para la caracterización y catalogación de los datos subyacentes.
                                            Debes responder ÚNICAMENTE con un objeto JSON válido, estrictamente delimitado por las claves solicitadas, sin añadir introducciones, explicaciones ni bloques de texto adicionales fuera del JSON."""
                                            
                        prompt_usuario = f"""
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
                        response = ollama.chat(
                            model=modelo,
                            messages=[
                                {"role": "system", "content": prompt_sistema},
                                {"role": "user", "content": prompt_usuario}
                            ],
                            format='json',
                            options={'temperature': 0.2},
                            think = False
                        )
            
                        # Extraemos métricas puras de inferencia
                        tiempo_inferencia = response.get('eval_duration', 0) / 1e9
                        tokens_generados = response.get('eval_count', 0)
                        tokens_por_segundo = tokens_generados / tiempo_inferencia if tiempo_inferencia > 0 else 0
                        
                        try:
                                        
                            datos_json = json.loads(response['message']['content'])
                            datos_json["tiempo_inferencia"] = f"{tiempo_inferencia:.2f}"
                            datos_json["tokens_generados"] = tokens_generados 
                            datos_json["tokens_por_segundo"] = f"{tokens_por_segundo:.2f}"
                                        
                            with open(f"{ruta_guardar_archivos_test}/{nombre_archivo}_articulo.json", "w", encoding="utf-8") as f:
                                json.dump(datos_json, f, ensure_ascii=False, indent=4)
                                                   
                        except json.JSONDecodeError:
                                print(f"Error: La respuesta generada por {modelo} no es un JSON válido.")
                                print(f"Contenido generado:\n{response['message']['content']}")
                                continue
                    
            except Exception as e:
                        print(f"Error en la inferencia con {modelo}: {e}")
        
        

    # 3. Limpieza inmediata de la VRAM para este modelo al terminar sus archivos
    try:
        ollama.chat(
            model=modelo,
            messages=[{'role': 'user', 'content': 'clean'}],
            options={'keep_alive': 0},
            think = False
        )
        print(f"VRAM liberada para {modelo}.\n" + "="*40 + "\n")
    except Exception as e:
        print(f"Aviso al limpiar VRAM de {modelo}: {e}")