# Crea un archivo convert_to_base64.py
import base64

# Leer el archivo pickle
with open('token_agente.pickle', 'rb') as f:
    pickle_data = f.read()

# Convertir a base64
base64_data = base64.b64encode(pickle_data).decode('utf-8')

# Guardar en archivo de texto
with open('token_base64.txt', 'w') as f:
    f.write(base64_data)

print("✅ Conversión exitosa! Archivo guardado como token_base64.txt")