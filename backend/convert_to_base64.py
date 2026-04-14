# convert_json_to_base64.py
import base64

# Leer el archivo JSON
with open('project-8613700d-20b9-4550-967-55335ad500b4.json', 'rb') as f:  # ← Cambia el nombre del archivo
    json_data = f.read()

# Convertir a base64
base64_data = base64.b64encode(json_data).decode('utf-8')

# Guardar en archivo de texto
with open('token_base64.txt', 'w') as f:
    f.write(base64_data)

print("✅ Conversión exitosa! Archivo guardado como gcs_credentials_base64.txt")
print(f"📋 Tamaño: {len(base64_data)} caracteres")
print("\n🔑 Copia este contenido a tu variable de entorno GCS_CREDENTIALS_BASE64")

