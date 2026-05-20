from easyDataverse import Dataverse

BASE_URL = "http://localhost:8080" 

# Reemplaza este token de ejemplo por tu API Token real del Dataverse de Oxford
API_TOKEN = "43cd9b2f-126f-4f88-b8ab-da3e2f2b909b" 

print(f"🔄 Conectando a {BASE_URL} y descargando bloques de metadatos...")

# Inicializa la conexión (aquí es donde antes fallaba)
dataverse = Dataverse(server_url=BASE_URL, api_token=API_TOKEN)

print("¡Conexión establecida con éxito! Ya puedes operar con el Dataverse de Oxford.")