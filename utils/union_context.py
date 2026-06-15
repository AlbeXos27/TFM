def unir_contextos(estrategia_contexto, contexto_art, contexto_dataset_manual):
    
    if estrategia_contexto == "Solo Artículo":
        prompt_segmento = f"CONTEXTO BASE DEL ARTÍCULO DE REFERENCIA:\n\"{contexto_art}\""
        instruccion_segmento = "Relaciona las variables y campos del dataset estrictamente con el marco teórico y las hipótesis analíticas del artículo."
    elif estrategia_contexto == "Solo Contexto Manual del Dataset":
        prompt_segmento = f"CONTEXTO MANUAL OPERATIVO DEL USUARIO:\n\"{contexto_dataset_manual}\""
        instruccion_segmento = "Explica detalladamente cómo la estructura y tipos de campos de este dataset sirven para medir u operacionalizar este contexto manual."
    else:  
        prompt_segmento = f"""
            [MARCO ACADÉMICO DEL PAPER]: "{contexto_art}"
            [ENFOQUE / ANOTACIONES DEL USUARIO]: "{contexto_dataset_manual}"
            """
        instruccion_segmento = """Ejecuta conceptualmente los siguientes pasos antes de redactar:
            1. Encuentra el puente teórico que conecta el paper académico con las notas prácticas del usuario.
            2. Explica analíticamente cómo los campos del archivo del dataset permiten ejecutar empíricamente esa conexión o complementar la investigación."""
            
    return prompt_segmento, instruccion_segmento