import os
import json
import re
import time
import httpx
from pathlib import Path
from urllib.parse import urljoin
from easyDataverse import Dataverse
from easyDataverse.license import License
from client_ia.request_IA import extraer_subjects

# Evita que dvuploader agrupe varios ficheros en un "package_N.zip" temporal:
# en Windows, dvuploader (dependencia de easyDataverse) abre ese zip con
# open() y nunca cierra el handle explícitamente (dvuploader/file.py,
# get_handler()), por lo que al terminar la subida su
# tempfile.TemporaryDirectory() falla al borrar el fichero con
# "WinError 32: el proceso no tiene acceso al archivo porque está siendo
# utilizado por otro proceso". Forzando el umbral de empaquetado a 1 byte,
# cada fichero se sube individualmente (sin zip intermedio) y el bug no se
# activa. Se respeta si el usuario ya definió la variable explícitamente.
os.environ.setdefault("DVUPLOADER_MAX_PKG_SIZE", "1")


def _cargar_registro_urls(ruta_registro):
    if not ruta_registro.exists():
        return {}
    try:
        with open(ruta_registro, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ No se pudo leer el registro de URLs de Dataverse '{ruta_registro}': {e}")
        return {}


def _registrar_url_dataverse(registro, ruta_registro, carpeta_nombre, nombre_dataset, dataset_pid, server_url):
    """
    Guarda la URL pública del dataset de Dataverse asociada a un dataset físico,
    para que el paso de indexación (utils/creacion_embedding.py) pueda mostrarla
    como enlace clicable en los resultados de busqueda.py.
    """
    if not nombre_dataset or not dataset_pid:
        return

    dataset_url = urljoin(server_url, f"dataset.xhtml?persistentId={dataset_pid}")
    clave = f"{carpeta_nombre}::{nombre_dataset}"
    registro[clave] = dataset_url

    try:
        with open(ruta_registro, "w", encoding="utf-8") as f:
            json.dump(registro, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ No se pudo escribir el registro de URLs de Dataverse: {e}")


def resolver_licencia_dataverse(identificador_portable, config):
    """
    Traduce el identificador de licencia portable y agnóstico al repositorio
    (ver utils/licencias.py, p.ej. 'CC-BY-4.0') a la licencia real activa en
    esta instancia de Dataverse, cruzando por su 'rightsIdentifier' (SPDX)
    contra el endpoint público '/api/licenses'.

    Si la licencia no está activa en esta instancia (o el identificador es
    'Other'/vacío), se devuelve None y Dataverse aplicará su licencia por
    defecto para el dataset.
    """
    if not identificador_portable or identificador_portable == "Other":
        return None

    server_url = config.get("DATAVERSE_URL", "")
    try:
        respuesta = httpx.get(f"{server_url.rstrip('/')}/api/licenses", timeout=5)
        respuesta.raise_for_status()
        licencias = respuesta.json().get("data", [])
        for lic in licencias:
            if lic.get("rightsIdentifier", "").lower() == identificador_portable.lower():
                return License.model_validate(lic)
    except Exception as e:
        print(f"⚠️ No se pudo consultar las licencias de '{server_url}': {e}")
        return None

    print(
        f"⚠️ La licencia '{identificador_portable}' no está activa en esta instancia de Dataverse. "
        "Se usará la licencia por defecto del servidor."
    )
    return None


def _esperar_desbloqueo_dataset(dataset_pid, config, timeout=180, intervalo=3):
    """
    Espera (sondeando '/locks') a que un dataset recién creado quede libre de
    bloqueos antes de intentar modificarlo. Justo tras la creación, Dataverse
    puede mantenerlo bloqueado mientras ingiere los ficheros adjuntos (p.ej.
    conversión de CSV a .tab), lo cual puede tardar bastante más que unos
    pocos segundos si el fichero es grande o el servidor está ocupado.
    """
    server_url = config.get("DATAVERSE_URL", "").rstrip("/")
    headers = {"X-Dataverse-key": config.get("API_TOKEN", "")}
    transcurrido = 0
    while transcurrido < timeout:
        try:
            respuesta = httpx.get(
                f"{server_url}/api/datasets/:persistentId/locks",
                params={"persistentId": dataset_pid},
                headers=headers,
                timeout=10,
            )
            respuesta.raise_for_status()
            if not respuesta.json().get("data", []):
                return
        except Exception:
            # Si no se puede consultar el estado de bloqueo, seguimos con el
            # sondeo por tiempo en vez de abortar aquí.
            pass
        time.sleep(intervalo)
        transcurrido += intervalo

    print(f"⚠️ El dataset {dataset_pid} sigue bloqueado tras {timeout}s de espera.")


def _aplicar_licencia_tras_creacion(dataset_pid, licencia, config):
    """
    Asigna la licencia a un dataset ya creado mediante el endpoint dedicado
    de Dataverse ('PUT /api/datasets/:persistentId/license').

    Es necesario hacerlo así (en vez de asignar 'dataset.license' antes de
    subir) porque easyDataverse 0.4.4 serializa ese campo como un string
    plano en el JSON de creación del dataset en vez del objeto {name, uri}
    que espera la API, y Dataverse lo ignora silenciosamente.

    Si tras los reintentos no se puede asignar, se lanza una excepción en
    vez de continuar en silencio: de lo contrario el dataset queda publicado
    con la licencia por defecto del servidor (CC0) sin que nadie se entere,
    y el pipeline lo marca igualmente como subida exitosa (ver
    ejecutar_pipeline_dataverse), por lo que nunca se reintentaría.
    """
    if licencia is None or not dataset_pid:
        return

    _esperar_desbloqueo_dataset(dataset_pid, config)

    server_url = config.get("DATAVERSE_URL", "").rstrip("/")
    intentos = 6
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            respuesta = httpx.put(
                f"{server_url}/api/datasets/:persistentId/license",
                params={"persistentId": dataset_pid},
                headers={"X-Dataverse-key": config.get("API_TOKEN", "")},
                json={"name": licencia.name, "uri": licencia.uri},
                timeout=10,
            )
            respuesta.raise_for_status()
            print(f"   ✓ Licencia '{licencia.name}' asignada al dataset.")
            return
        except httpx.HTTPStatusError as e:
            # El dataset puede seguir bloqueado justo tras su creación mientras
            # Dataverse procesa la ingesta de los ficheros adjuntos (p.ej.
            # conversión a .tab); reintentamos antes de darnos por vencidos.
            cuerpo = e.response.text[:300] if e.response is not None else ""
            ultimo_error = f"{e} — {cuerpo}"
            if intento < intentos:
                print(f"   ⏳ Licencia no asignada aún (intento {intento}/{intentos}, {e.response.status_code if e.response is not None else '?'}): {cuerpo}. Reintentando...")
                time.sleep(3 * intento)
                continue
        except Exception as e:
            ultimo_error = str(e)
            if intento < intentos:
                print(f"   ⏳ Error al asignar la licencia (intento {intento}/{intentos}): {e}. Reintentando...")
                time.sleep(3 * intento)
                continue

    raise RuntimeError(
        f"No se pudo asignar la licencia '{licencia.name}' al dataset {dataset_pid} "
        f"tras {intentos} intentos: {ultimo_error}"
    )

def buscar_archivo_en_carpeta(ruta_carpeta, nombre_archivo, subcarpetas=None):
    """Busca un archivo dentro de la carpeta raíz o en subcarpetas conocidas."""
    rutas_a_buscar = [ruta_carpeta]
    if subcarpetas:
        rutas_a_buscar.extend(ruta_carpeta / sub for sub in subcarpetas)

    for base in rutas_a_buscar:
        ruta_candidato = base / nombre_archivo
        if ruta_candidato.exists():
            return ruta_candidato
    return None


def cargar_configuracion(ruta_config="config.json"):
    """Lee el archivo de configuración JSON desde la misma carpeta del script."""
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    ruta_config_absoluta = os.path.join(directorio_actual, ruta_config)
    
    if not os.path.exists(ruta_config_absoluta):
        raise FileNotFoundError(f"❌ No se encontró el archivo de configuración: {ruta_config_absoluta}")
        
    with open(ruta_config_absoluta, "r", encoding="utf-8") as f:
        return json.load(f)


def ejecutar_pipeline_dataverse(config):
    """
    Escanea un directorio en busca de carpetas con 'metadatos.json' y sube
    cada carpeta como un único dataset de Dataverse (título = nombre de la
    carpeta/proyecto) directamente a la colección raíz configurada, sin
    crear subcolecciones por proyecto. Devuelve un resumen del proceso.
    """
    resumen = {
        "carpetas_totales_detectadas": 0,
        "carpetas_procesadas_con_exito": 0,
        "carpetas_saltadas": 0,
        "carpetas_con_error": 0,
        "articulos_subidos_nuevos": 0,
        "articulos_saltados_duplicados": 0
    }

    print("🔄 Conectando con la API de Dataverse...")
    try:
        dv = Dataverse(
            server_url=config.get("DATAVERSE_URL"), 
            api_token=config.get("API_TOKEN")
        )
    except Exception as e:
        print(f"❌ Error crítico al conectar con Dataverse: {e}")
        return resumen

    dir_investigaciones = Path(config.get("DIRECTORIO_INVESTIGACIONES", "investigaciones"))
    if not dir_investigaciones.exists():
        print(f"❌ Error: La carpeta raíz '{dir_investigaciones}' no existe.")
        return resumen

    archivo_registro = config.get("ARCHIVO_REGISTRO", "pids.txt")
    raiz_coleccion = config.get("PARENT_COLLECTION")  # Colección madre (ej: "root" o "giiuca")

    # Datos de contacto obligatorios
    contacto_nombre = config.get("CONTACT_NAME", "Gestor de Investigación")
    contacto_email = config.get("CONTACT_EMAIL", "admin@dataverse.local")

    # Cargar registros ya procesados
    titulos_procesados = set()
    if os.path.exists(archivo_registro):
        with open(archivo_registro, "r", encoding="utf-8") as f:
            for linea in f:
                linea_limpia = linea.strip()
                if linea_limpia:
                    titulos_procesados.add(linea_limpia)

    # Registro de URLs de Dataverse por dataset físico (carpeta::nombre_dataset -> URL
    # pública), para que utils/creacion_embedding.py pueda mostrarlo en las búsquedas.
    ruta_registro_urls = Path(config.get("REGISTRO_URLS", "dataverse_urls.json"))
    registro_urls = _cargar_registro_urls(ruta_registro_urls)

    # 1. BUCLE DE CARPETAS
    for ruta_carpeta in dir_investigaciones.iterdir():
        if not ruta_carpeta.is_dir():
            continue
            
        resumen["carpetas_totales_detectadas"] += 1
        ruta_json = ruta_carpeta / "metadatos.json"
        
        if not ruta_json.exists():
            print(f"⏩ Saltando carpeta '{ruta_carpeta.name}': No contiene 'metadatos.json'")
            resumen["carpetas_saltadas"] += 1
            continue
            
        print(f"\n🚀 Procesando carpeta de investigación: {ruta_carpeta.name.upper()}")
        print("=" * 60)
        
        try:
            with open(ruta_json, "r", encoding="utf-8") as f:
                meta = json.load(f)
            
            # El título del dataset de Dataverse es el nombre que el usuario le dio
            # a la carpeta/proyecto en la UI (paso 3, "Nombre carpeta").
            proyecto_nombre = meta.get("proyecto_nombre", ruta_carpeta.name).strip()
            titulo_dataset = proyecto_nombre or ruta_carpeta.name

            articulos = meta.get("articulos", [])
            datasets_globales = meta.get("datasets", [])

            if not articulos and not datasets_globales:
                print(f"⚠️ La carpeta {ruta_carpeta.name} no contiene ni artículos ni datasets.")
                resumen["carpetas_saltadas"] += 1
                continue

            print(f"\n📦 [{titulo_dataset}] Evaluando carpeta completa como un único dataset...")

            if titulo_dataset in titulos_procesados:
                print("⏩ Saltando: Ya fue subida previamente.")
                resumen["articulos_saltados_duplicados"] += 1
                resumen["carpetas_procesadas_con_exito"] += 1
                continue

            # =================================================================
            # UN ÚNICO DATASET DE DATAVERSE POR CARPETA, SUBIDO DIRECTAMENTE A
            # LA COLECCIÓN RAÍZ CONFIGURADA (sin crear subcolecciones por proyecto)
            # =================================================================
            dataset = dv.create_dataset()
            dataset.citation.title = titulo_dataset
            dataset.citation.add_dataset_contact(name=contacto_nombre, email=contacto_email)

            nombres_autores_agregados = set()
            subjects_acumulados = []
            licencia_elegida = ""
            archivos_ya_adjuntados = set()
            archivos_dataset_fisicos = []

            # --- ARTÍCULOS: descripción, autores, subjects, licencia, DOI y PDF ---
            for idx, articulo in enumerate(articulos, start=1):
                titulo_articulo = articulo.get("titulo_documento", "").strip() or f"Artículo {idx}"
                contexto = articulo.get("contexto_general", "").strip()
                if contexto:
                    dataset.citation.add_ds_description(value=contexto)
                    subjects_acumulados.extend(extraer_subjects(contexto, titulo_articulo))

                # Los autores del artículo NO se añaden como autores del dataset:
                # solo deben figurar en la publicación relacionada (add_publication,
                # más abajo), para no mezclarlos con los autores reales del dataset.
                autores = articulo.get("autores", [])

                if not licencia_elegida:
                    licencia_elegida = articulo.get("licencia", "").strip()

                # Publicación relacionada (DOI del artículo original)
                doi_articulo = articulo.get("doi", "").strip()
                if doi_articulo:
                    doi_limpio = re.sub(r"^(https?://doi\.org/|doi:)", "", doi_articulo, flags=re.IGNORECASE).strip()
                    nombres_autores_articulo = [a.get("nombre", "") for a in autores if isinstance(a, dict) and a.get("nombre")] if isinstance(autores, list) else []
                    citacion = (", ".join(nombres_autores_articulo) + ". " if nombres_autores_articulo else "") + f"{titulo_articulo}."
                    try:
                        dataset.citation.add_publication(
                            relation_type="IsSupplementTo",
                            citation=citacion,
                            id_type="doi",
                            id_number=doi_limpio,
                            url=f"https://doi.org/{doi_limpio}",
                        )
                        print(f"   ✓ Publicación relacionada vinculada (DOI: {doi_limpio})")
                    except Exception as e_pub:
                        print(f"⚠️ No se pudo añadir la publicación relacionada (DOI '{doi_limpio}'): {e_pub}")

                pdf_nombre = articulo.get("nombre_articulo")
                if pdf_nombre and pdf_nombre not in archivos_ya_adjuntados:
                    fichero_pdf = buscar_archivo_en_carpeta(ruta_carpeta, pdf_nombre, subcarpetas=["articulos"])
                    if fichero_pdf is not None:
                        partes_descripcion_pdf = [f"Documento académico original: {pdf_nombre}"]
                        if contexto:
                            partes_descripcion_pdf.append(contexto)

                        relaciones_datasets_articulo = articulo.get("relaciones_datasets", [])
                        if isinstance(relaciones_datasets_articulo, list):
                            for relacion in relaciones_datasets_articulo:
                                texto_relacion = relacion.get("relacion_con_contexto", "").strip()
                                if texto_relacion and texto_relacion != "Sin relación generada.":
                                    nombre_dataset_relacionado = relacion.get("nombre_dataset", "")
                                    partes_descripcion_pdf.append(
                                        f"Relación con '{nombre_dataset_relacionado}': {texto_relacion}"
                                    )

                        dataset.add_file(local_path=str(fichero_pdf), description="\n\n".join(partes_descripcion_pdf))
                        archivos_ya_adjuntados.add(pdf_nombre)
                        print(f"   ✓ PDF vinculado: {pdf_nombre}")
                    else:
                        print(f"   ⚠️ PDF no encontrado: {pdf_nombre}")

            # --- DATASETS FÍSICOS: descripción, autores, subjects, licencia y fichero ---
            for ds in datasets_globales:
                archivo_nombre = ds.get("nombre_dataset", "")
                if not archivo_nombre:
                    continue

                archivos_dataset_fisicos.append(archivo_nombre)

                descripcion_ds = ds.get("analisis_contextual", "").strip() or ds.get("explicacion_estructura", "").strip()
                if descripcion_ds:
                    dataset.citation.add_ds_description(value=descripcion_ds)
                    subjects_acumulados.extend(extraer_subjects(descripcion_ds, archivo_nombre))

                autores_ds = ds.get("autores", [])
                if isinstance(autores_ds, list):
                    for autor_data in autores_ds:
                        nombre = autor_data.get("nombre")
                        if nombre and nombre not in nombres_autores_agregados:
                            orcid = autor_data.get("orcid", "").strip()
                            dataset.citation.add_author(
                                name=nombre,
                                identifier_scheme="ORCID" if orcid else None,
                                identifier=orcid if orcid else None,
                            )
                            nombres_autores_agregados.add(nombre)

                if not licencia_elegida:
                    licencia_elegida = ds.get("licencia", "").strip()

                if archivo_nombre not in archivos_ya_adjuntados:
                    ruta_fichero_datos = buscar_archivo_en_carpeta(ruta_carpeta, archivo_nombre, subcarpetas=["datasets"])
                    if ruta_fichero_datos is not None:
                        dataset.add_file(local_path=str(ruta_fichero_datos), description=ds.get("explicacion_estructura", "Archivo de datos."))
                        archivos_ya_adjuntados.add(archivo_nombre)
                        print(f"   ✓ Dataset vinculado: {archivo_nombre}")
                    else:
                        print(f"   ⚠️ Dataset no encontrado: {archivo_nombre}")

            # --- CAMPOS OBLIGATORIOS: fallback si nada aportó descripción/autor/subject ---
            if not nombres_autores_agregados:
                print("⚠️ Ningún autor detectado en la carpeta. Asignando autor por defecto.")
                dataset.citation.add_author(name=contacto_nombre)

            if not dataset.citation.ds_description:
                dataset.citation.add_ds_description(value="Conjunto de datos de investigación.")

            subjects_dedup = []
            for subject in subjects_acumulados:
                if subject not in subjects_dedup:
                    subjects_dedup.append(subject)
            dataset.citation.subject = subjects_dedup if subjects_dedup else ["Other"]

            print(f"📤 Transmitiendo datos hacia la colección '{raiz_coleccion}'...")
            dataset_pid = dataset.upload(dataverse_name=raiz_coleccion)
            _aplicar_licencia_tras_creacion(
                dataset_pid,
                resolver_licencia_dataverse(licencia_elegida, config),
                config,
            )

            with open(archivo_registro, "a", encoding="utf-8") as f:
                f.write(f"{titulo_dataset}\n")
            titulos_procesados.add(titulo_dataset)
            for nombre_ds_fisico in archivos_dataset_fisicos:
                _registrar_url_dataverse(
                    registro_urls, ruta_registro_urls, ruta_carpeta.name,
                    nombre_ds_fisico, dataset_pid, config.get("DATAVERSE_URL", ""),
                )
            print(f"🎉 ¡Éxito! Creado en Dataverse. PID: {dataset_pid}")
            resumen["articulos_subidos_nuevos"] += 1
            resumen["carpetas_procesadas_con_exito"] += 1
                
        except Exception as e:
            print(f"❌ Error procesando la carpeta '{ruta_carpeta.name}': {e}")
            resumen["carpetas_con_error"] += 1

    print("\n🏁 Pipeline masivo finalizado.")
    return resumen
