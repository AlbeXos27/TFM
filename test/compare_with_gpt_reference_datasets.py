from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
except Exception:
    np = None
    SentenceTransformer = None


ROOT = Path(__file__).resolve().parent
REFERENCE_MODEL = "gpt-5.4-mini"
MODEL_FOLDERS = [
    "granite4.1_3b",
    "llama3.2_3b",
    "qwen3.5_4b",
]
DATASET_ROOTS = [
    ROOT / "datasets_no_article",
    ROOT / "datasets_with_article",
]
EXPECTED_KEYS = {
    "proposito_general",
    "explicacion_campos",
    "posibles_uso",
    "palabras_clave",
    "subject",
}


def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    text = str(text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: Any) -> set[str]:
    cleaned = normalize_text(text)
    return set(re.findall(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ0-9]+", cleaned))


def list_to_set(values: Any) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, list):
        return {normalize_text(v) for v in values if normalize_text(v)}
    return {normalize_text(values)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


EMBEDDER_MODEL = "BAAI/bge-m3"
EMBEDDER = None
EMBEDDER_ERROR = None


def get_embedder() -> SentenceTransformer | None:
    global EMBEDDER, EMBEDDER_ERROR

    if SentenceTransformer is None or np is None:
        return None

    if EMBEDDER is None and EMBEDDER_ERROR is None:
        try:
            EMBEDDER = SentenceTransformer(EMBEDDER_MODEL)
        except Exception as exc:
            EMBEDDER_ERROR = exc
            return None

    if EMBEDDER_ERROR is not None:
        return None

    return EMBEDDER


def semantic_similarity(a: Any, b: Any) -> float:
    text_a = normalize_text(a)
    text_b = normalize_text(b)

    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0

    embedder = get_embedder()
    if embedder is None:
        return similarity_text(text_a, text_b)

    try:
        vectors = embedder.encode([text_a, text_b], convert_to_numpy=True)
        vec_a = np.asarray(vectors[0], dtype=float)
        vec_b = np.asarray(vectors[1], dtype=float)
        denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
        if denom == 0:
            return 0.0
        return float(np.dot(vec_a, vec_b) / denom)
    except Exception:
        return similarity_text(text_a, text_b)


def purpose_similarity(a: Any, b: Any) -> float:
    text_similarity = similarity_text(a, b)
    semantic = semantic_similarity(a, b)
    return round(0.55 * semantic + 0.45 * text_similarity, 4)


def similarity_text(a: Any, b: Any) -> float:
    text_a = normalize_text(a)
    text_b = normalize_text(b)
    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0
    return SequenceMatcher(None, text_a, text_b).ratio()


def similarity_list_like(a: Any, b: Any) -> float:
    list_a = [normalize_text(item) for item in (a if isinstance(a, list) else [a]) if normalize_text(item)]
    list_b = [normalize_text(item) for item in (b if isinstance(b, list) else [b]) if normalize_text(item)]

    text_a = " ".join(list_a)
    text_b = " ".join(list_b)

    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0

    token_a = tokenize(text_a)
    token_b = tokenize(text_b)
    token_overlap = jaccard(token_a, token_b)
    semantic = semantic_similarity(text_a, text_b)

    return round(0.7 * semantic + 0.3 * token_overlap, 4)


def structure_quality(cand: dict[str, Any]) -> float:
    if not isinstance(cand, dict):
        return 0.0

    checks: list[float] = []

    # Validaciones básicas de los campos obligatorios
    checks.append(1.0 if isinstance(cand.get("proposito_general"), str) and cand["proposito_general"].strip() else 0.0)
    checks.append(1.0 if isinstance(cand.get("subject"), str) and cand["subject"].strip() else 0.0)
    checks.append(1.0 if isinstance(cand.get("palabras_clave"), list) and len(cand["palabras_clave"]) > 0 else 0.0)
    checks.append(1.0 if isinstance(cand.get("posibles_uso"), list) and len(cand["posibles_uso"]) > 0 else 0.0)

    # Obtenemos los valores de formato_tabla y explicacion_campos
    formato_tabla = cand.get("formato_tabla")
    explicacion = cand.get("explicacion_campos")

    # Validación condicional según formato_tabla
    if formato_tabla is True:
        # Si es true, miramos obligatoriamente que sea una lista con las llaves requeridas
        if isinstance(explicacion, list):
            if explicacion:
                valid_items = sum(
                    1
                    for item in explicacion
                    if isinstance(item, dict)
                    and all(key in item for key in ("campo", "tipo_dato", "explicacion"))
                    and item["campo"].strip()
                    and item["tipo_dato"].strip()
                    and item["explicacion"].strip()
                )
                checks.append(valid_items / len(explicacion))
            else:
                checks.append(0.0)
        else:
            checks.append(0.0)
    else:
        # Si formato_tabla es false (o no es true), miramos si es una cadena escrita completa
        checks.append(1.0 if isinstance(explicacion, str) and explicacion.strip() else 0.0)

    return round(sum(checks) / len(checks), 4)


def compute_score(ref: dict[str, Any], cand: dict[str, Any]) -> dict[str, float]:
    schema_coverage = sum(1 for key in EXPECTED_KEYS if key in cand) / len(EXPECTED_KEYS)

    prop_similarity = purpose_similarity(ref.get("proposito_general"), cand.get("proposito_general"))
    subject_similarity = purpose_similarity(ref.get("subject"), cand.get("subject"))

    keyword_similarity = similarity_list_like(ref.get("palabras_clave"), cand.get("palabras_clave"))
    use_similarity = similarity_list_like(ref.get("posibles_uso"), cand.get("posibles_uso"))
    structure = structure_quality(cand)

    explanation_ok = 1.0 if isinstance(cand.get("explicacion_campos"), (list, str)) else 0.0

    final_score = (
        0.25 * prop_similarity
        + 0.15 * subject_similarity
        + 0.10 * keyword_similarity
        + 0.05 * use_similarity
        + 0.20 * structure
        + 0.20 * schema_coverage
        + 0.05 * explanation_ok
    ) * 100

    return {
        "proposito_general": round(prop_similarity * 100, 2),
        "subject": round(subject_similarity * 100, 2),
        "palabras_clave": round(keyword_similarity * 100, 2),
        "posibles_uso": round(use_similarity * 100, 2),
        "estructura": round(structure * 100, 2),
        "schema_coverage": round(schema_coverage * 100, 2),
        "explanation_ok": round(explanation_ok * 100, 2),
        "final_score": round(final_score, 2),
    }


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def evaluate_model(model_name: str, dataset_root: Path) -> list[dict[str, Any]]:
    reference_root = dataset_root / REFERENCE_MODEL / "files_from_test"
    model_root = dataset_root / model_name / "files_from_test"

    results: list[dict[str, Any]] = []

    for ref_path in sorted(reference_root.glob("*.json")):
        if ref_path.name.endswith("_articulo.json"):
            continue

        target_name = ref_path.name
        candidate_path = model_root / target_name
        if not candidate_path.exists():
            results.append(
                {
                    "archivo": target_name,
                    "estado": "faltante",
                    "motivo": "No existe en el modelo objetivo",
                    "score": 0.0,
                    "tiempo_inferencia": None,
                    "tokens_generados": None,
                    "tokens_por_segundo": None,
                }
            )
            continue

        ref_data = load_json(ref_path)
        cand_data = load_json(candidate_path)
        scored = compute_score(ref_data, cand_data)

        # Extracción de métricas de rendimiento con conversión segura de tipos
        try:
            tiempo_inf = float(cand_data.get("tiempo_inferencia")) if cand_data.get("tiempo_inferencia") is not None else None
        except (ValueError, TypeError):
            tiempo_inf = None

        try:
            tok_gen = int(cand_data.get("tokens_generados")) if cand_data.get("tokens_generados") is not None else None
        except (ValueError, TypeError):
            tok_gen = None

        try:
            tok_sec = float(cand_data.get("tokens_por_segundo")) if cand_data.get("tokens_por_segundo") is not None else None
        except (ValueError, TypeError):
            tok_sec = None

        results.append(
            {
                "archivo": target_name,
                "estado": "ok",
                "motivo": "Comparado con referencia",
                "score": scored["final_score"],
                "details": scored,
                "tiempo_inferencia": tiempo_inf,
                "tokens_generados": tok_gen,
                "tokens_por_segundo": tok_sec,
            }
        )

    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [item["score"] for item in results if item.get("score") is not None]
    tiempos = [item["tiempo_inferencia"] for item in results if item.get("tiempo_inferencia") is not None]
    tokens = [item["tokens_generados"] for item in results if item.get("tokens_generados") is not None]
    tokens_seg = [item["tokens_por_segundo"] for item in results if item.get("tokens_por_segundo") is not None]

    if not scores:
        return {
            "count": 0,
            "avg_score": 0.0,
            "max_score": 0.0,
            "min_score": 0.0,
            "avg_tiempo_inferencia": 0.0,
            "avg_tokens_generados": 0.0,
            "avg_tokens_por_segundo": 0.0,
        }

    return {
        "count": len(results),
        "avg_score": round(sum(scores) / len(scores), 2),
        "max_score": round(max(scores), 2),
        "min_score": round(min(scores), 2),
        "avg_tiempo_inferencia": round(sum(tiempos) / len(tiempos), 2) if tiempos else 0.0,
        "avg_tokens_generados": round(sum(tokens) / len(tokens), 2) if tokens else 0.0,
        "avg_tokens_por_segundo": round(sum(tokens_seg) / len(tokens_seg), 2) if tokens_seg else 0.0,
    }


def main() -> None:
    print("Comparando salidas de modelos frente a la referencia gpt-5.4-mini...\n")

    all_summaries: list[dict[str, Any]] = []
    for dataset_root in DATASET_ROOTS:
        for model_name in MODEL_FOLDERS:
            results = evaluate_model(model_name, dataset_root)
            summary = summarize(results)
            all_summaries.append(
                {
                    "dataset_root": dataset_root.name,
                    "model": model_name,
                    "summary": summary,
                    "results": results,
                }
            )

            print(f"[{dataset_root.name}] {model_name}")
            print(f"  archivos evaluados: {summary['count']}")
            print(f"  score medio: {summary['avg_score']}")
            print(f"  mejor: {summary['max_score']}")
            print(f"  peor: {summary['min_score']}")
            print(f"  tiempo medio inferencia: {summary['avg_tiempo_inferencia']} s")
            print(f"  tokens generados (medio): {summary['avg_tokens_generados']}")
            print(f"  tokens/seg (medio): {summary['avg_tokens_por_segundo']}\n")

            output_path = dataset_root / model_name / f"comparison_vs_{REFERENCE_MODEL}.json"
            with output_path.open("w", encoding="utf-8") as fp:
                json.dump({"summary": summary, "results": results}, fp, ensure_ascii=False, indent=4)

            print(f"  resumen guardado en: {output_path}\n")


if __name__ == "__main__":
    main()