from .API_DATAVERSE.dataverse import cargar_configuracion, ejecutar_pipeline_dataverse
    
    
def upload_files_to_dataverse():
    """
    Función principal para cargar la configuración y ejecutar el pipeline de Dataverse.
    """
    config = cargar_configuracion()
    return ejecutar_pipeline_dataverse(config)