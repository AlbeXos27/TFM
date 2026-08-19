from pathlib import Path
import hashlib
import json
import pandas as pd

from utils.licencias import LICENCIA_POR_DEFECTO


def _formatear_analisis_dataset(analisis):
    """Convierte el dict de análisis generado por el LLM (proposito_general,
    explicacion_campos, posibles_uso, palabras_clave) en un texto legible."""
    if not analisis:
        return ""
    if isinstance(analisis, str):
        return analisis.strip()

    partes = []

    proposito = analisis.get("proposito_general", "")
    if proposito:
        partes.append(proposito.strip())

    campos = analisis.get("explicacion_campos", "")
    if isinstance(campos, list):
        for campo in campos:
            nombre = campo.get("campo", "")
            tipo = campo.get("tipo_dato", "")
            explicacion = campo.get("explicacion", "")
            partes.append(f"{nombre} ({tipo}): {explicacion}")
    elif isinstance(campos, str) and campos.strip():
        partes.append(campos.strip())

    posibles_uso = analisis.get("posibles_uso", [])
    if posibles_uso:
        partes.append("Posibles usos: " + ", ".join(posibles_uso))

    palabras_clave = analisis.get("palabras_clave", [])
    if palabras_clave:
        partes.append("Palabras clave: " + ", ".join(palabras_clave))

    return "\n".join(partes)


def _calcular_hash_sha256(json_salida):
    """Calcula el SHA-256 del contenido de metadatos.json (contenido generado,
    no incluye el propio campo de hash) para certificar su integridad."""
    contenido_canonico = json.dumps(json_salida, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(contenido_canonico.encode("utf-8")).hexdigest()


def _cargar_info_certificacion_ia():
    """Recupera qué modelos IAG (Ollama) se usaron para generar el contenido,
    a partir de config.json, para dejar constancia de autoría del hallazgo."""
    try:
        with open("./config.json", "r", encoding="utf-8") as archivo:
            config = json.load(archivo)
    except Exception as e:
        print(f"No se pudo cargar el archivo de configuración: {e}")
        config = {}

    return {
        "modelo_dataset": config.get("modelo_dataset", ""),
        "modelo_articulo": config.get("modelo_articulo", ""),
        "fecha_generacion": str(pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")),
    }


def guardar_json(datasets_dict, articulos_dict,st):
    
    nombres_incompletos = any(
        not config.get("nombre") for config in st.session_state.carpetas_destino
    )
    
    if nombres_incompletos:
        st.warning("Por favor, complete los nombres de todas las carpetas.")
    else:
        for idx, config_carpeta in enumerate(st.session_state.carpetas_destino):
            nombre_carpeta = config_carpeta["nombre"] or f"proyecto_{idx + 1}"
            ruta_final = Path(".") / "investigaciones" / nombre_carpeta
            ruta_final.mkdir(parents=True, exist_ok=True)

            (ruta_final / "datasets").mkdir(exist_ok=True)
            (ruta_final / "articulos").mkdir(exist_ok=True)

            for d_name in config_carpeta.get("datasets_seleccionados", []):
                if d_name in datasets_dict:
                    archivo = datasets_dict[d_name]
                    if hasattr(archivo, "seek"):
                        archivo.seek(0)
                    with open(ruta_final / "datasets" / d_name, "wb") as f:
                        f.write(archivo.getbuffer())

            for p_name in config_carpeta.get("pdfs_seleccionados", []):
                if p_name in articulos_dict:
                    # Obtenemos los metadatos guardados del artículo
                    meta_art = st.session_state.metadatos_articulos_editados.get(p_name, {})
                    print(f"Metadatos del artículo '{p_name}': {list(meta_art.keys())}")
                    # Verificamos si el toggle "subir_archivo" es True (por defecto True si no existe)
                    debe_guardar_pdf = meta_art.get("subir_archivo", True)
                    
                    if debe_guardar_pdf:
                        with open(ruta_final / "articulos" / p_name, "wb") as f:
                            f.write(articulos_dict[p_name])
                    else:
                        st.info(f"El artículo '{p_name}' no se guardará físicamente por configuración del usuario.")
                        
                        
            # Construcción estructural del JSON de salida
            json_salida = {
                "proyecto_nombre": nombre_carpeta,
                "fecha": str(pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")),
                "articulos": [],
                "datasets": [],
                "estrategia_altmetrics": config_carpeta.get("altmetrics", {}),
                "certificacion_ia": _cargar_info_certificacion_ia(),
            }

            relaciones = config_carpeta.get("relaciones_cruzadas", {})

            if config_carpeta.get("pdfs_seleccionados", []):
                for p_name in config_carpeta["pdfs_seleccionados"]:
                    meta_art = (
                        st.session_state.metadatos_articulos_editados.get(
                            p_name, {}
                        )
                    )
                    lista_autores_art = meta_art.get(
                        "autores_finales_seleccionados", []
                    )

                    autores_art_json = (
                        ""
                        if not lista_autores_art
                        else [
                            {
                                "nombre": autor_nom,
                                "orcid": meta_art.get("orcids_vinculados", {}).get(autor_nom, ""),
                            }
                            for autor_nom in lista_autores_art
                        ]
                    )

                    estructura_articulo = {
                        "nombre_articulo": p_name,
                        "titulo_documento": meta_art.get("title", p_name),
                        "contexto_general": meta_art.get("contexto_unico", "").strip(),
                        "licencia": meta_art.get("licencia", LICENCIA_POR_DEFECTO),
                        "doi": meta_art.get("doi", "").strip(),
                        "autores": autores_art_json,
                        "relaciones_datasets": [],
                    }

                    for d_name in config_carpeta.get(
                        "datasets_seleccionados", []
                    ):
                        texto_relacion = ""
                        if (
                            p_name in relaciones and d_name in relaciones[p_name]
                        ):
                            texto_relacion = relaciones[p_name][d_name].strip()

                        estructura_articulo["relaciones_datasets"].append(
                            {
                                "nombre_dataset": d_name,
                                "relacion_con_contexto": (
                                    texto_relacion if texto_relacion else "Sin relación generada."
                                ),
                            }
                        )

                    json_salida["articulos"].append(estructura_articulo)

            for d_name in config_carpeta.get("datasets_seleccionados", []):
                meta_ds = st.session_state.metadatos_datasets_editados.get(d_name, {})
                lista_autores_ds = meta_ds.get("autores_finales_seleccionados", [])

                autores_ds_json = (
                    ""
                    if not lista_autores_ds
                    else [
                        {
                            "nombre": a_nom,
                            "orcid": meta_ds.get("orcids_vinculados", {}).get(a_nom, ""),
                        }
                        for a_nom in lista_autores_ds
                    ]
                )

                analisis_estructural = _formatear_analisis_dataset(
                    st.session_state.analisis_datasets.get(d_name, {})
                )
                contexto_manual = st.session_state.contextos_datasets.get(d_name, "").strip()

                relacion_aislada = ""
                if (
                    not config_carpeta.get("pdfs_seleccionados", [])
                    and "Sin Artículo" in relaciones
                ):
                    if d_name in relaciones["Sin Artículo"]:
                        relacion_aislada = relaciones["Sin Artículo"][d_name].strip()

                json_salida["datasets"].append(
                    {
                        "nombre_dataset": d_name,
                        "explicacion_estructura": analisis_estructural,
                        "contexto_specifico_manual": contexto_manual,
                        "analisis_contextual": (
                            relacion_aislada if relacion_aislada else ""
                        ),
                        "licencia": meta_ds.get("licencia", LICENCIA_POR_DEFECTO),
                        "autores": autores_ds_json,
                    }
                )

            json_salida["hash_integridad_sha256"] = _calcular_hash_sha256(json_salida)

            json_string = json.dumps(json_salida, indent=4, ensure_ascii=False)
            (ruta_final / "metadatos.json").write_text(json_string, encoding="utf-8")