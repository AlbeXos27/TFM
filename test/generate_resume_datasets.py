from __future__ import annotations

import json
from pathlib import Path
import matplotlib.pyplot as plt

# 1. Configuración de rutas y variables globales
ROOT = Path(__file__).resolve().parent

REFERENCE_MODEL = "gpt-5.4-mini"
MODEL_FOLDERS = [
    "qwen3.5_4b",
    "granite4.1_3b",
    "llama3.2_3b",
]

MODEL_PRETTY_NAMES = {
    "qwen3.5_4b": "Qwen 3.5 4B",
    "granite4.1_3b": "Granite 4.1 3B",
    "llama3.2_3b": "Llama 3.2 3B",
}

DATASET_SOURCES = [
    (ROOT / "datasets_no_article", "Sin Artículo"),
    (ROOT / "datasets_with_article", "Con Artículo"),
]

METRICS_KEYS = [
    "final_score",
    "proposito_general",
    "subject",
    "palabras_clave",
    "posibles_uso",
    "estructura",
    "schema_coverage",
    "explanation_ok",
]

METRICS_HEADERS = [
    "Final",
    "Propósito",
    "Subject",
    "Keywords",
    "Usos",
    "Estruct.",
    "Cofert.",
    "Expl. OK",
]

# Métricas adicionales de rendimiento
PERF_KEYS = [
    "tiempo_inferencia",
    "tokens_generados",
    "tokens_por_segundo",
]

PERF_HEADERS = [
    "Tiempo (s)",
    "Tokens Gen.",
    "Tok/s",
]


def load_dataset_from_folder(dataset_dir: Path, origen_label: str) -> list[dict]:
    """Carga los resultados JSON de una carpeta específica."""
    if not dataset_dir.exists():
        print(f"⚠️ Advertencia: No existe la carpeta {dataset_dir}")
        return []

    files_data: dict[str, dict[str, dict]] = {}

    for model_name in MODEL_FOLDERS:
        json_path = (
            dataset_dir
            / model_name
            / f"comparison_vs_{REFERENCE_MODEL}.json"
        )
        if not json_path.exists():
            continue

        with json_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        for res in data.get("results", []):
            archivo = res.get("archivo")
            details = res.get("details")
            if archivo and details:
                # Extraemos y combinamos detalles de calidad con métricas de rendimiento
                combined_info = dict(details)

                # Helper para conversión segura de tipos
                def parse_val(val, target_type):
                    try:
                        return target_type(val) if val is not None else None
                    except (ValueError, TypeError):
                        return None

                combined_info["tiempo_inferencia"] = parse_val(res.get("tiempo_inferencia"), float)
                combined_info["tokens_generados"] = parse_val(res.get("tokens_generados"), int)
                combined_info["tokens_por_segundo"] = parse_val(res.get("tokens_por_segundo"), float)

                if archivo not in files_data:
                    files_data[archivo] = {}
                files_data[archivo][model_name] = combined_info

    datasets_data = []
    for archivo, models_dict in files_data.items():
        datasets_data.append({
            "archivo": archivo,
            "origen": origen_label,
            "models_dict": models_dict
        })

    return datasets_data


def compute_model_averages(datasets_data: list[dict]) -> dict[str, dict[str, float]]:
    """Calcula la media exacta de cada métrica (calidad y rendimiento) para cada modelo."""
    all_keys = METRICS_KEYS + PERF_KEYS
    model_totals = {m_key: {k: 0.0 for k in all_keys} for m_key in MODEL_FOLDERS}
    model_counts = {m_key: {k: 0 for k in all_keys} for m_key in MODEL_FOLDERS}

    for item in datasets_data:
        models_dict = item["models_dict"]
        for model_key in MODEL_FOLDERS:
            if model_key in models_dict:
                details = models_dict[model_key]
                for k in all_keys:
                    val = details.get(k)
                    if val is not None:
                        model_totals[model_key][k] += float(val)
                        model_counts[model_key][k] += 1

    model_averages = {}
    for model_key in MODEL_FOLDERS:
        model_averages[model_key] = {}
        for k in all_keys:
            count = model_counts[model_key][k]
            if count > 0:
                model_averages[model_key][k] = model_totals[model_key][k] / count
            else:
                model_averages[model_key][k] = 0.0

    return model_averages


def export_files_table_image(
    datasets_data: list[dict], 
    output_image_path: Path, 
    title_suffix: str = "",
    include_origen_col: bool = True
):
    """Genera la imagen PNG de la tabla comparativa POR ARCHIVOS."""
    if not datasets_data:
        return

    table_data = []
    bold_cells = []

    if include_origen_col:
        headers = ["Archivo Evaluado", "Tipo / Origen", "Modelo"] + METRICS_HEADERS
        col_offset = 3
    else:
        headers = ["Archivo Evaluado", "Modelo"] + METRICS_HEADERS
        col_offset = 2

    row_index = 0

    for item in datasets_data:
        archivo_name = item["archivo"]
        origen = item["origen"]
        models_dict = item["models_dict"]

        max_per_metric = {}
        for m in METRICS_KEYS:
            vals = [
                models_dict[m_key][m]
                for m_key in MODEL_FOLDERS
                if m_key in models_dict and m in models_dict[m_key]
            ]
            max_per_metric[m] = max(vals) if vals else None

        for idx, model_key in enumerate(MODEL_FOLDERS):
            model_display = MODEL_PRETTY_NAMES.get(model_key, model_key)
            file_display = archivo_name if idx == 0 else ""
            
            if include_origen_col:
                origen_display = origen if idx == 0 else ""
                row = [file_display, origen_display, model_display]
            else:
                row = [file_display, model_display]

            details = models_dict.get(model_key, {})

            for col_idx, m_key in enumerate(METRICS_KEYS):
                val = details.get(m_key, 0.0)
                row.append(f"{val:.2f}")

                if val == max_per_metric[m_key] and val > 0:
                    bold_cells.append((row_index, col_idx + col_offset))

            table_data.append(row)
            row_index += 1

    fig, ax = plt.subplots(
        figsize=(18 if include_origen_col else 16, len(table_data) * 0.45 + 1.2), dpi=300
    )
    ax.axis("off")

    table = ax.table(
        cellText=table_data,
        colLabels=headers,
        cellLoc="center",
        loc="center",
    )

    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    for col_idx in range(len(headers)):
        cell = table[(0, col_idx)]
        cell.set_facecolor("#2c3e50")
        cell.get_text().set_color("white")
        cell.get_text().set_weight("bold")
        cell.set_height(0.05)

    num_rows = len(table_data)
    for r in range(num_rows):
        cell_file = table[(r + 1, 0)]
        cell_file.get_text().set_ha("left")
        cell_file.get_text().set_weight("bold")

        bg_color = "#f8f9fa" if (r // len(MODEL_FOLDERS)) % 2 == 0 else "#ffffff"

        for c in range(len(headers)):
            cell = table[(r + 1, c)]
            cell.set_facecolor(bg_color)
            cell.set_edgecolor("#e0e0e0")

            if (r, c) in bold_cells:
                cell.get_text().set_weight("bold")
                cell.get_text().set_color("#1b5e20")

    plt.tight_layout()

    plt.savefig(output_image_path, bbox_inches="tight", dpi=300)
    plt.close()
    print(f"✅ Tabla de archivos guardada en: {output_image_path}")


def export_averages_table_image(
    datasets_data: list[dict], 
    output_image_path: Path, 
    title_suffix: str = ""
):
    """Genera la imagen PNG EXCLUSIVA de la TABLA DE PROMEDIOS POR MODELO (incluyendo rendimiento)."""
    if not datasets_data:
        return

    model_averages = compute_model_averages(datasets_data)
    
    headers = ["Modelo Evaluado"] + METRICS_HEADERS + PERF_HEADERS
    all_keys = METRICS_KEYS + PERF_KEYS

    # Definimos qué métricas se consideran "mejor cuando es más alto"
    # Para tiempo de inferencia, menor suele ser mejor, pero marcamos el máximo rendimiento (Tokens/s)
    max_avg_per_metric = {}
    for m in all_keys:
        vals = [model_averages[m_key][m] for m_key in MODEL_FOLDERS]
        max_avg_per_metric[m] = max(vals) if vals else None

    table_data = []
    bold_cells = []

    for row_index, model_key in enumerate(MODEL_FOLDERS):
        model_display = MODEL_PRETTY_NAMES.get(model_key, model_key)
        row = [model_display]
        avg_details = model_averages.get(model_key, {})

        for col_idx, m_key in enumerate(all_keys):
            val = avg_details.get(m_key, 0.0)
            row.append(f"{val:.2f}")

            # +1 de desfase por la columna 'Modelo Evaluado'
            # Destacamos en negrita los valores más altos (excluyendo tiempo_inferencia si no se requiere)
            if m_key != "tiempo_inferencia" and val == max_avg_per_metric[m_key] and val > 0:
                bold_cells.append((row_index, col_idx + 1))

        table_data.append(row)

    # Ajustamos el ancho para acomodar las 3 columnas adicionales
    fig, ax = plt.subplots(figsize=(15, 3.2), dpi=300)
    ax.axis("off")

    table = ax.table(
        cellText=table_data,
        colLabels=headers,
        cellLoc="center",
        loc="center",
    )

    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    table.scale(1.2, 2.0)

    # Estilizado de Cabecera (Azul Oscuro)
    for col_idx in range(len(headers)):
        cell = table[(0, col_idx)]
        cell.set_facecolor("#1a365d")
        cell.get_text().set_color("white")
        cell.get_text().set_weight("bold")

    # Estilizado de Celdas
    num_rows = len(table_data)
    for r in range(num_rows):
        cell_model = table[(r + 1, 0)]
        cell_model.get_text().set_weight("bold")

        bg_color = "#f7fafc" if r % 2 == 0 else "#ffffff"

        for c in range(len(headers)):
            cell = table[(r + 1, c)]
            cell.set_facecolor(bg_color)
            cell.set_edgecolor("#cbd5e0")

            if (r, c) in bold_cells:
                cell.get_text().set_weight("bold")
                cell.get_text().set_color("#1b5e20")

    plt.tight_layout()

    plt.savefig(output_image_path, bbox_inches="tight", dpi=300)
    plt.close()
    print(f"📊 Tabla independiente de promedios guardada en: {output_image_path}")


def main():
    all_combined_data = []

    # 1. Procesar carpeta por carpeta
    for dataset_dir, origen_label in DATASET_SOURCES:
        folder_data = load_dataset_from_folder(dataset_dir, origen_label)
        
        if folder_data:
            # A) Tabla por archivos dentro de la carpeta
            out_files_png = dataset_dir / "tabla_comparativa_archivos.png"
            export_files_table_image(
                folder_data, 
                out_files_png, 
                title_suffix=f"({origen_label})", 
                include_origen_col=False
            )

            # B) Tabla APARTE de promedios dentro de la carpeta
            out_avg_png = dataset_dir / "tabla_promedios_modelos.png"
            export_averages_table_image(
                folder_data, 
                out_avg_png, 
                title_suffix=f"({origen_label})"
            )

            all_combined_data.extend(folder_data)

    # 2. Generar las tablas unificadas en la raíz del proyecto
    if all_combined_data:
        # A) Tabla combinada completa de archivos
        out_combined_files = ROOT / "tabla_comparativa_combinada_archivos.png"
        export_files_table_image(
            all_combined_data, 
            out_combined_files, 
            title_suffix="(Todas las carpetas)", 
            include_origen_col=True
        )

        # B) Tabla APARTE del promedio global unificado
        out_combined_avg = ROOT / "tabla_promedios_globales.png"
        export_averages_table_image(
            all_combined_data, 
            out_combined_avg, 
            title_suffix="(Global - Todos los Datasets)"
        )


if __name__ == "__main__":
    main()