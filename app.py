import streamlit as st
from ui.join_context_dataset import ui_join_context_dataset
from ui.upload_articles import ui_upload_articles
from ui.upload_dataset import ui_upload_datasets

API_KEY_GROQ = st.secrets["API_KEY_GROQ"]
MODELO_LLM = st.secrets["MODELO_LLM"]
st.set_page_config(layout="wide")

# Inicialización segura de st.session_state
if 'analisis_datasets' not in st.session_state:
    st.session_state.analisis_datasets = {}
if 'contextos_datasets' not in st.session_state:
    st.session_state.contextos_datasets = {}
if 'metadatos_articulos_editados' not in st.session_state:
    st.session_state.metadatos_articulos_editados = {}
if 'metadatos_datasets_editados' not in st.session_state:
    st.session_state.metadatos_datasets_editados = {}
if 'textos_articulos' not in st.session_state:
    st.session_state.textos_articulos = {}


st.title("Extracción de Contexto y Enlace Académico")
st.header("1. Datasets")

datasets_dict = {}
ui_upload_datasets(datasets_dict, st)

st.header("2. Artículos")
articulos_dict = {}
ui_upload_articles(articulos_dict, st)

if datasets_dict or st.session_state.analisis_datasets:
    ui_join_context_dataset(datasets_dict, articulos_dict, st)

