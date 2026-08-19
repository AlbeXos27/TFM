"""Catálogo de licencias agnóstico al repositorio de destino.

Cada dataset/artículo se etiqueta con un identificador portable (estilo
SPDX). El mapeo a la licencia real de cada plataforma de publicación
(Dataverse, Zenodo, etc.) se resuelve únicamente en el paso de subida
específico de esa plataforma, para que este catálogo no dependa de ningún
backend concreto.
"""

CATALOGO_LICENCIAS = [
    {"id": "CC0-1.0", "nombre": "CC0 1.0 — Dominio público"},
    {"id": "CC-BY-4.0", "nombre": "CC BY 4.0 — Atribución"},
    {"id": "CC-BY-SA-4.0", "nombre": "CC BY-SA 4.0 — Atribución CompartirIgual"},
    {"id": "CC-BY-NC-4.0", "nombre": "CC BY-NC 4.0 — Atribución No Comercial"},
    {"id": "CC-BY-ND-4.0", "nombre": "CC BY-ND 4.0 — Atribución SinDerivadas"},
    {"id": "CC-BY-NC-SA-4.0", "nombre": "CC BY-NC-SA 4.0"},
    {"id": "CC-BY-NC-ND-4.0", "nombre": "CC BY-NC-ND 4.0"},
    {"id": "MIT", "nombre": "MIT License"},
    {"id": "Apache-2.0", "nombre": "Apache License 2.0"},
    {"id": "GPL-3.0", "nombre": "GNU GPL v3.0"},
    {"id": "Other", "nombre": "Otra / Términos personalizados"},
]

LICENCIA_POR_DEFECTO = "CC-BY-4.0"


def nombre_legible(licencia_id):
    """Devuelve el nombre legible de un identificador de licencia portable."""
    for licencia in CATALOGO_LICENCIAS:
        if licencia["id"] == licencia_id:
            return licencia["nombre"]
    return licencia_id
