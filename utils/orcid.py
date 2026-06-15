from turtle import st

import requests
import streamlit as st


def buscar_en_orcid_real(nombre_autor):
    url = f"https://pub.orcid.org/v3.0/expanded-search/?q=text:{nombre_autor}"
    headers = {"Accept": "application/json"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            data = response.json()
            listado_resultados = ["Selecciona un resultado del listado..."]
            
            if isinstance(data, dict):
                for item in data.get("expanded-result", []):
                    if isinstance(item, dict):
                        orcid_id = item.get("orcid-id")
                        given_names = item.get("given-names", "")
                        family_names = item.get("family-names", "")
                        
                        inst_list = []
                        if isinstance(item.get("institution-name"), list):
                            inst_list = [inst.get("institution-name", "") for inst in item.get("institution-name", []) if isinstance(inst, dict) and inst.get("institution-name")]
                        
                        inst_str = f" ({', '.join(inst_list)})" if any(inst_list) else ""
                        listado_resultados.append(f"{orcid_id} - {given_names} {family_names}{inst_str}")
                
            if len(listado_resultados) == 1:
                return ["No se encontraron coincidencias en el registro de ORCID."]
            return listado_resultados
        else:
            return [f"Aviso: Servidor ORCID no disponible (Status {response.status_code})"]
    except Exception as e:
        return [f"Aviso: Sin conexión con ORCID ({str(e)})"]
    
def actualizar_orcid_ds(ds_key, aut_key, sb_k,st):
    sel = st.session_state[sb_k]
    if sel and "000" in sel:
        cod = sel.split(" - ")[0].strip()
        st.session_state.metadatos_datasets_editados[ds_key]["orcids_vinculados"][aut_key] = cod
        st.session_state[f"final_orcid_ds_{ds_key}_{aut_key}"] = cod
        
def actualizar_orcid_seleccionado(art_key, autor_key, sb_key,st):
    seleccion = st.session_state[sb_key]
    if seleccion and "000" in seleccion:
        codigo_extraido = seleccion.split(" - ")[0].strip()
        st.session_state.metadatos_articulos_editados[art_key]["orcids_vinculados"][autor_key] = codigo_extraido
        st.session_state[f"final_orcid_{art_key}_{autor_key}"] = codigo_extraido
