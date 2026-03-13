from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException
from qdrant_client.models import VectorParams, Distance, PointStruct, PayloadSchemaType
from sentence_transformers import SentenceTransformer
import uuid
import time
from config import QDRANT_API_KEY, QDRANT_URL, QDRANT_COLLECTION_NAME

COLLECTION_NAME = QDRANT_COLLECTION_NAME
VECTOR_SIZE = 384

client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
    timeout=30,
    prefer_grpc=False
)

embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


# --- Validar que la colección tiene la config correcta ---
def _is_collection_config_valid() -> bool:
    """Verifica que la colección existe y tiene vectores regulares de tamaño correcto."""
    try:
        info = client.get_collection(COLLECTION_NAME)
        vectors_config = info.config.params.vectors

        # Si es dict → es multi-vector (configuración incorrecta)
        if isinstance(vectors_config, dict):
            print(f"⚠️ Colección '{COLLECTION_NAME}' tiene configuración multi-vector. Debe recrearse.")
            return False

        # Si el tamaño no coincide → configuración incorrecta
        if vectors_config.size != VECTOR_SIZE:
            print(f"⚠️ Colección '{COLLECTION_NAME}' tiene size={vectors_config.size}, esperado={VECTOR_SIZE}. Debe recrearse.")
            return False

        return True

    except Exception as e:
        print(f"⚠️ No se pudo verificar config de colección: {e}")
        return False


# --- Inicializar colección con retry y validación ---
def init_collection(max_retries=3):
    for attempt in range(max_retries):
        try:
            collections = client.get_collections().collections
            collection_exists = COLLECTION_NAME in [c.name for c in collections]

            if collection_exists:
                if _is_collection_config_valid():
                    print(f"ℹ️ Colección '{COLLECTION_NAME}' ya existe y su configuración es correcta")
                else:
                    # Config inválida → recrear
                    print(f"🗑️ Recreando colección '{COLLECTION_NAME}' por configuración incompatible...")
                    client.delete_collection(COLLECTION_NAME)
                    collection_exists = False

            if not collection_exists:
                client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
                )
                print(f"✅ Colección '{COLLECTION_NAME}' creada en Qdrant")

            # Crear índices para filtrado
            for field, schema in [
                ("user_id", PayloadSchemaType.KEYWORD),
                ("conversation_id", PayloadSchemaType.KEYWORD),
                ("role", PayloadSchemaType.KEYWORD),
            ]:
                try:
                    client.create_payload_index(
                        collection_name=COLLECTION_NAME,
                        field_name=field,
                        field_schema=schema
                    )
                    print(f"✅ Índice '{field}' creado/verificado")
                except Exception as e:
                    print(f"ℹ️ Índice '{field}' ya existe o error: {e}")

            return True

        except Exception as e:
            print(f"❌ Error inicializando Qdrant (intento {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
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
                time.sleep(1)
            else:
                print("⚠️ No se pudo guardar en Qdrant. Continuando sin almacenar.")
                return None


# --- Buscar contexto relevante con retry ---
def search_context(query, user_id=None, conversation_id=None, limit=10, score_threshold=0.5, max_retries=3):
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    for attempt in range(max_retries):
        try:
            query_vector = embedder.encode(query).tolist()

            conditions = []
            if user_id:
                conditions.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))
            if conversation_id:
                conditions.append(FieldCondition(key="conversation_id", match=MatchValue(value=conversation_id)))

            query_filter = Filter(must=conditions) if conditions else None

            results = client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold
            )

            context_texts = [hit.payload["text"] for hit in results]
            print(f"✅ Contexto encontrado: {len(context_texts)} mensajes (threshold={score_threshold})")
            return context_texts

        except (ResponseHandlingException, Exception) as e:
            print(f"❌ Error buscando en Qdrant (intento {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                print("⚠️ No se pudo buscar en Qdrant. Retornando contexto vacío.")
                return []


# --- Verificar conexión ---
def test_qdrant_connection():
    try:
        collections = client.get_collections()
        print(f"✅ Conexión a Qdrant exitosa. Colecciones: {len(collections.collections)}")
        return True
    except Exception as e:
        print(f"❌ Error conectando a Qdrant: {e}")
        return False


# --- Inicialización lazy ---
_collection_initialized = False

def ensure_collection_initialized():
    global _collection_initialized
    if not _collection_initialized:
        _collection_initialized = init_collection()
    return _collection_initialized

try:
    ensure_collection_initialized()
except Exception as e:
    print(f"⚠️ Error en inicialización automática de Qdrant: {e}")