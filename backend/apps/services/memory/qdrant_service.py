from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from qdrant_client.http.exceptions import ResponseHandlingException
from sentence_transformers import SentenceTransformer
import uuid
import time
from config import QDRANT_API_KEY, QDRANT_URL, QDRANT_COLLECTION_NAME

# -- Configuracion Qdrant --
COLLECTION_NAME = QDRANT_COLLECTION_NAME

# Cliente Qdrant con timeout y retry
client = QdrantClient(
    url=QDRANT_URL, 
    api_key=QDRANT_API_KEY,
    timeout=30,  # Timeout de 30 segundos
    prefer_grpc=False  # Usar HTTP en lugar de gRPC si hay problemas
)

# Modelo de embeddings local (gratis)
embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# --- Inicializar colección con retry ---
def init_collection(max_retries=3):
    for attempt in range(max_retries):
        try:
            collections = client.get_collections().collections
            if COLLECTION_NAME not in [c.name for c in collections]:
                client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE)
                )
                print(f"✅ Colección '{COLLECTION_NAME}' creada en Qdrant")
            else:
                print(f"ℹ️ Colección '{COLLECTION_NAME}' ya existe")
            return True
        except Exception as e:
            print(f"❌ Error inicializando Qdrant (intento {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Backoff exponencial
            else:
                print("⚠️ No se pudo inicializar Qdrant. Continuando sin base vectorial.")
                return False

# --- Guardar texto en Qdrant con retry ---
def store_message(text, metadata=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            vector = embedder.encode(text).tolist()
            point_id = str(uuid.uuid4())
            
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={"text": text, **(metadata or {})}
                    )
                ]
            )
            print(f"✅ Mensaje guardado en Qdrant: {point_id}")
            return point_id
            
        except (ResponseHandlingException, Exception) as e:
            print(f"❌ Error guardando en Qdrant (intento {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)  # Esperar 1 segundo antes del retry
            else:
                print("⚠️ No se pudo guardar en Qdrant. Continuando sin almacenar.")
                return None

# --- Buscar contexto relevante con retry ---
def search_context(query, limit=3, max_retries=3):
    for attempt in range(max_retries):
        try:
            query_vector = embedder.encode(query).tolist()
            results = client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                limit=limit
            )
            return [hit.payload["text"] for hit in results]
            
        except (ResponseHandlingException, Exception) as e:
            print(f"❌ Error buscando en Qdrant (intento {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                print("⚠️ No se pudo buscar en Qdrant. Retornando contexto vacío.")
                return []

# --- Función para verificar conexión ---
def test_qdrant_connection():
    try:
        collections = client.get_collections()
        print(f"✅ Conexión a Qdrant exitosa. Colecciones: {len(collections.collections)}")
        return True
    except Exception as e:
        print(f"❌ Error conectando a Qdrant: {e}")
        return False

# Inicialización lazy - solo cuando sea necesario
_collection_initialized = False

def ensure_collection_initialized():
    global _collection_initialized
    if not _collection_initialized:
        _collection_initialized = init_collection()
    return _collection_initialized

# Para compatibilidad, mantener la inicialización automática pero con manejo de errores
try:
    ensure_collection_initialized()
except Exception as e:
    print(f"⚠️ Error en inicialización automática de Qdrant: {e}")