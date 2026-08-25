# TFM — Pipeline de curación y búsqueda semántica de repositorios de investigación

> Trabajo de Fin de Máster: pipeline que convierte datasets y artículos académicos en un repositorio de investigación curado, enriquecido con metadatos generados por IA y publicado en Dataverse, junto con un buscador semántico sobre el contenido indexado.

El proyecto automatiza el flujo completo de curación de datos de investigación: desde la subida de datasets y PDFs, pasando por la extracción de metadatos y relaciones mediante modelos de lenguaje ejecutados **100% en local** (Ollama, sin dependencia de APIs externas ni claves), hasta la publicación en una instancia de [Dataverse](https://dataverse.org/) y la indexación en una base vectorial para búsqueda semántica.

## Índice

- [Características](#características)
- [Arquitectura](#arquitectura)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Uso](#uso)
- [Evaluación de modelos](#evaluación-de-modelos)

## Características

- **Ingesta guiada de datasets y artículos** (CSV/XLSX/TXT, PDF, por archivo o URL) con una interfaz Streamlit paso a paso.
- **Extracción automática de metadatos con LLMs locales**: estructura y contexto de datasets, título/autores/DOI de artículos, y relaciones cruzadas dataset↔artículo, todo generado por modelos Ollama (`qwen3.5`, `granite4.1`, etc.) sin enviar datos a servicios externos.
- **Reconciliación de autoría asistida**: combina autores detectados en metadatos del PDF, extraídos por el LLM y añadidos manualmente, con enlace opcional a **ORCID**.
- **Gestión de licencias portable** basada en identificadores SPDX (`CC-BY-4.0`, etc.), resueltos al modelo de licencias específico de la instancia de Dataverse en el momento de la publicación.
- **Organización en "carpetas" de proyecto**: agrupación de varios datasets y artículos relacionados en una única publicación, con generación de descripciones cruzadas y estrategias configurables de fusión de contexto.
- **Publicación automática en Dataverse** (autores, descripciones, licencia, ficheros de datos y PDFs) mediante `easyDataverse`, con control de duplicados entre ejecuciones.
- **Buscador semántico independiente** sobre el repositorio indexado: expansión de consultas por LLM, embeddings (`BAAI/bge-m3`), fusión de resultados y *reranking* con un modelo *cross-encoder* (`BAAI/bge-reranker-v2-m3`).
- **Benchmarking de modelos**: scripts para comparar la calidad de extracción de metadatos de varios modelos locales frente a una referencia GPT.

## Arquitectura

El proyecto consta de **dos aplicaciones Streamlit independientes** que no comparten proceso:

| Aplicación | Rol |
|---|---|
| `app.py` | Pipeline de ingesta: subir → analizar → relacionar → publicar en Dataverse |
| `busqueda.py` | Interfaz de búsqueda semántica *standalone* sobre el índice de ChromaDB |

### Flujo de la pipeline de ingesta (`app.py`)

```
1. Subida de datasets (ui/upload_dataset.py)
   → análisis de estructura/autoría vía LLM, licencia, ORCID

2. Subida de artículos (ui/upload_articles.py)
   → extracción de texto (pypdf), metadatos vía LLM, licencia, ORCID

3. Agrupación en carpetas de proyecto (ui/join_context_dataset.py)
   → relaciones cruzadas dataset↔artículo generadas por LLM
   → "Guardar Todo":
        utils/save_json.py          (persistencia local + metadatos.json)
          → upload_platform/upload_to_platform.py   (publicación en Dataverse)
              → utils/creacion_embedding.py          (indexación en ChromaDB)
```

Todas las llamadas a modelos de lenguaje viven en `client_ia/request_IA.py`, que construye prompts en español exigiendo salida JSON estricta y aplica *fallbacks* seguros si una llamada falla (sin reintentos, sin romper la ejecución de Streamlit).

### Persistencia

Cada carpeta de proyecto se guarda en `investigaciones/<nombre>/` con sus datasets, artículos y un `metadatos.json` canónico (título, autores, contexto, relaciones, licencia, DOI y hash de integridad SHA-256).

### Búsqueda (`busqueda.py`)

```
consulta del usuario
   → expansión a 4-6 conceptos relacionados (LLM, Ollama)
   → embedding de consulta + conceptos (BAAI/bge-m3)
   → búsqueda en ChromaDB por cada concepto
   → fusión ponderada de resultados
   → reranking con cross-encoder (BAAI/bge-reranker-v2-m3)
   → filtrado por umbral fijo
```

### Integración con Dataverse

`upload_platform/API_DATAVERSE/dataverse.py` recorre `investigaciones/` y publica **un dataset de Dataverse por carpeta** en la colección raíz configurada, adjuntando artículos (PDF) y datasets (ficheros de datos), aplicando la licencia resuelta y evitando republicar carpetas ya subidas (`pids.txt`). Las URLs públicas de cada fichero se registran en `dataverse_urls.json` para mostrarlas en los resultados de búsqueda.

## Estructura del repositorio

```
.
├── app.py                       # Pipeline de ingesta (Streamlit)
├── busqueda.py                  # Buscador semántico (Streamlit)
├── config.json                  # Prompts y modelos de Ollama
├── client_ia/
│   └── request_IA.py            # Todas las llamadas a Ollama
├── ui/
│   ├── upload_dataset.py        # Paso 1: datasets
│   ├── upload_articles.py       # Paso 2: artículos
│   └── join_context_dataset.py  # Paso 3: carpetas de proyecto
├── utils/
│   ├── extract_abstract.py      # Extracción de texto de PDFs
│   ├── orcid.py                 # Enlace con la API pública de ORCID
│   ├── licencias.py             # Catálogo portable de licencias (SPDX)
│   ├── union_context.py         # Estrategias de fusión de contexto
│   ├── save_json.py             # Persistencia de carpetas de proyecto
│   └── creacion_embedding.py    # Indexación en ChromaDB
├── upload_platform/
│   ├── upload_to_platform.py
│   └── API_DATAVERSE/
│       ├── dataverse.py         # Lógica de publicación en Dataverse
│       └── eliminar_duplicados_dataverse.py  # Script destructivo manual
├── test/                        # Benchmarking de modelos locales vs. GPT
├── investigaciones/             # Proyectos generados (no versionado)
└── chroma_db/                   # Índice vectorial de ChromaDB
```

## Requisitos previos

- Python 3.13
- [Ollama](https://ollama.com/) instalado y en ejecución local, con los modelos configurados en `config.json` (p.ej. `qwen3.5:4b`, `granite4.1:3b`) ya descargados (`ollama pull <modelo>`)
- Una instancia de Dataverse accesible (local o remota) con un token de API válido, para el paso de publicación
- GPU NVIDIA con drivers CUDA (recomendado, para acelerar embeddings/reranker). El proyecto usa PyTorch compilado para **CUDA 13.2** (`cu132`); en una GPU/driver distinto hay que ajustar el índice de instalación (ver más abajo)

## Instalación

### 1. Crear el entorno virtual

```powershell
python -m venv env
env\Scripts\activate
```

### 2. Instalar PyTorch (con soporte CUDA)

`torch==2.12.0+cu132` es una build específica de CUDA que **no está en PyPI**, solo en el índice propio de PyTorch. Por eso se instala aparte, antes que el resto de dependencias:

```powershell
pip install "torch==2.12.0+cu132" "torchvision==0.27.0" --index-url https://download.pytorch.org/whl/cu132
```

> Si tu GPU/driver usa otra versión de CUDA, cambia `cu132` por la que corresponda (p.ej. `cu121`, `cu124`...) en la URL y en la versión de `torch`/`torchvision` de `requirements.txt`. Para instalar solo CPU, usa en su lugar `pip install torch torchvision` sin `--index-url` (más lento en inferencia).

### 3. Instalar el resto de dependencias

```powershell
pip install -r requirements.txt
```

### 4. Configurar Dataverse

Edita `upload_platform/API_DATAVERSE/config.json` con `DATAVERSE_URL`, `API_TOKEN`, `PARENT_COLLECTION` y datos de contacto de tu instancia de Dataverse. **Este archivo contiene un token de API — trátalo como secreto**.

## Uso

```powershell
env\Scripts\activate
streamlit run app.py        # pipeline de ingesta
streamlit run busqueda.py   # interfaz de búsqueda
```

Streamlit debe lanzarse desde la raíz del repositorio (usa `./config.json` con ruta relativa).

1. En `app.py`: sube tus datasets y artículos, revisa/edita los metadatos y autores propuestos por el LLM, agrúpalos en una carpeta de proyecto y pulsa **"Guardar Todo"** para persistir, publicar en Dataverse e indexar.
2. En `busqueda.py`: escribe una consulta en lenguaje natural y explora los resultados reordenados semánticamente, con enlace directo al dataset publicado en Dataverse.

## Evaluación de modelos

No hay una suite de tests automatizada (pytest); `test/` contiene scripts de benchmarking que se ejecutan de forma individual:

```powershell
python test/generate_files_to_test.py
python test/compare_with_gpt_reference_datasets.py
python test/generate_resume_datasets.py
```

Comparan la extracción de metadatos de varios modelos locales (llama3.2, qwen3.5, granite4.1) frente a una referencia GPT, usando similitud semántica (`BAAI/bge-m3`) y generando tablas/gráficas resumen.

Proyecto desarrollado como Trabajo de Fin de Máster.
