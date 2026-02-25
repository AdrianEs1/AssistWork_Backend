import json
from typing import Any
from apps.services.llm.llm_service import call_llm


class IntelligentContext:
    """Sistema de contexto inteligente que maneja automáticamente el mapeo entre métodos"""
    
    def __init__(self):
        self.data = {}
        self.method_results = []
        self.type_registry = {}
        self.resolution_counters = {}  # ✅ Ya lo tienes
    
    def reset_resolution_counters(self):
        """Reinicia los contadores de resolución al inicio de una nueva secuencia"""
        self.resolution_counters = {}
        print("🔄 Contadores de resolución reiniciados")
    
    def store_result(self, method_name: str, result: Any, method_signature: str = ""):
        """Almacena el resultado de un método con análisis automático"""
        result_info = {
            "method": method_name,
            "result": result,
            "signature": method_signature,
            "step": len(self.method_results)
        }
        
        self.method_results.append(result_info)
        
        # Análisis inteligente del resultado
        self._analyze_and_store_data(method_name, result)
        
        print(f"📦 Contexto actualizado por {method_name}")
        print(f"   Claves disponibles: {list(self.data.keys())}")


    async def resolve_dynamic_arguments_with_llm(
        self,
        method_name: str,
        args: dict,
        user_input: str
    ) -> dict:
        """
        Resuelve todos los argumentos marcados como 'dynamic' usando el contador
        para IDs y el LLM para parámetros semánticos.
        """

        # Detectar parámetros dinámicos
        dynamic_params = {
            k: v for k, v in args.items()
            if isinstance(v, str) and v.lower() == "dynamic"
        }

        if not dynamic_params:
            return {}

        if not hasattr(self, 'llm_service') or self.llm_service is None:
            raise RuntimeError("LLM service no está conectado al contexto")

        resolved = {}
        remaining_dynamic = {}

        # ✅ PASO 1: Resolver IDs con el contador secuencial (sin LLM)
        for param_name in dynamic_params:
            if param_name.endswith("_id"):
                id_value = self._resolve_id_parameter(param_name)
                if id_value is not None:
                    print(f"✅ '{param_name}' resuelto por contador: {id_value}")
                    resolved[param_name] = id_value
                else:
                    print(f"⚠️ '{param_name}' no pudo resolverse por contador, pasando al LLM")
                    remaining_dynamic[param_name] = "dynamic"
            else:
                remaining_dynamic[param_name] = "dynamic"

        # ✅ PASO 2: Si no quedan parámetros para el LLM, retornar directo
        if not remaining_dynamic:
            print(f"🎯 Todos los parámetros resueltos por contador: {resolved}")
            return resolved

        # ✅ PASO 3: Solo ir al LLM para parámetros semánticos (body, subject, to, etc.)
        context_snapshot = {
            k: v for k, v in self.data.items()
            if any(
                token in k.lower()
                for token in [
                    "content", "text", "email", "id", "subject", "body"
                ]
            )
        }

        print("🧠 Contexto enviado al LLM (argument resolver):")
        for k, v in context_snapshot.items():
            preview = str(v)
            print(f"  - {k}: {preview[:200]}{'...' if len(preview) > 200 else ''}")

        prompt = f"""
        Eres un resolvedor de argumentos para un orquestador de acciones.

        Tu única tarea es completar los valores de los parámetros marcados como "dynamic".

        REGLAS OBLIGATORIAS:
        - Devuelve SOLO un JSON válido
        - NO incluyas explicaciones
        - NO incluyas texto fuera del JSON
        - Para los correos utiliza la información correcta para reemplazar los valores de to, subject, body
        - NO inventes claves
        - USA EXCLUSIVAMENTE las claves listadas en "Parámetros a resolver"
        - Si no puedes resolver un valor con certeza, usa null

        Método a ejecutar:
        {method_name}

        Parámetros a resolver (estas son las ÚNICAS claves permitidas):
        {list(remaining_dynamic.keys())}

        Contexto disponible:
        {context_snapshot}

        Solicitud original del usuario:
        {user_input}

        EJEMPLOS DE RESPUESTA CORRECTA:

        Si los parámetros a resolver son:
        ["file_id"]

        Respuesta válida:
        {{
        "file_id": "1AbCDefGhIjK"
        }}

        Si los parámetros a resolver son:
        ["to", "subject", "body"]

        Respuesta válida:
        {{
        "to": "cliente@correo.com",
        "subject": "Invitación al evento",
        "body": "Estimado cliente, nos complace invitarle..."
        }}

        IMPORTANTE:
        - No reutilices estructuras de otros métodos
        - El formato SIEMPRE depende de los parámetros listados

        Devuelve el JSON final ahora.
        """

        try:
            from apps.services.llm.llm_service import call_llm
            raw_response = await call_llm(prompt)

            import json
            llm_resolved = json.loads(raw_response)
            print("Estamos en resolver dynamic arguments with LLM")

            if not isinstance(llm_resolved, dict):
                raise ValueError("El LLM no devolvió un objeto JSON")

            # ✅ PASO 4: Combinar lo resuelto por contador + lo resuelto por LLM
            resolved.update(llm_resolved)
            return resolved

        except Exception as e:
            raise RuntimeError(
                f"Error resolviendo argumentos dinámicos con LLM: {e}"
            )

    
    
    def _analyze_and_store_data(self, method_name: str, result: Any):
        """Analiza el resultado y extrae datos útiles automáticamente"""
        
        if isinstance(result, dict):
            self._extract_from_dict(method_name, result)
        elif isinstance(result, list):
            self._extract_from_list(method_name, result)
        elif isinstance(result, str):
            self._extract_from_string(method_name, result)

        # Acumular resultados en lista
        results_key = f"{method_name}_results"
        if results_key not in self.data:
            self.data[results_key] = []
        self.data[results_key].append(result)
        
        # Mantener último resultado
        self.data[f"{method_name}_result"] = result
    
    def _extract_from_dict(self, method_name: str, data: dict):
        """Extrae datos útiles de un diccionario con prioridad en content/body"""
        
        # 🔥 FIX 1: ACUMULAR listas de objetos con IDs
        for key, value in data.items():
            if isinstance(value, list) and value:
                # Si es lista de diccionarios con 'id'
                if isinstance(value[0], dict) and 'id' in value[0]:
                    ids = [item['id'] for item in value if 'id' in item]
                    
                    # 🔥 ACUMULAR en lugar de sobrescribir
                    generic_ids_key = f"{key}_ids"
                    if generic_ids_key not in self.data:
                        self.data[generic_ids_key] = []
                    self.data[generic_ids_key].extend(ids)
                    print(f"📝 IDs acumulados en '{generic_ids_key}': {self.data[generic_ids_key]}")
                    
                    # Acumular también con prefijo del método
                    method_ids_key = f"{method_name}_{key}_ids"
                    if method_ids_key not in self.data:
                        self.data[method_ids_key] = []
                    self.data[method_ids_key].extend(ids)
                    
                    # 🔥 Acumular objetos completos
                    generic_data_key = f"{key}_data"
                    if generic_data_key not in self.data:
                        self.data[generic_data_key] = []
                    self.data[generic_data_key].extend(value)
                    
                    method_data_key = f"{method_name}_{key}_data"
                    if method_data_key not in self.data:
                        self.data[method_data_key] = []
                    self.data[method_data_key].extend(value)
            
            # Buscar IDs individuales
            elif 'id' in key.lower():
                self.data[f"{method_name}_id"] = value
                self.data[f"last_id"] = value
        
        # Buscar content/body (ya estaba bien con acumulación)
        content_found = False
        for key, value in data.items():
            if key.lower() in ['content', 'body']:
                # Acumular contenidos
                contents_key = f"{method_name}_contents"
                if contents_key not in self.data:
                    self.data[contents_key] = []
                self.data[contents_key].append(value)

                # Mantener último
                self.data[f"{method_name}_content"] = value
                self.data[f"last_content"] = value
                content_found = True
                print(f"✅ Contenido principal detectado en clave '{key}' ({len(str(value))} caracteres)")
                break
        
        # Fallback a text/message
        if not content_found:
            for key, value in data.items():
                if key.lower() in ['text', 'message']:
                    self.data[f"{method_name}_content"] = value
                    self.data[f"last_content"] = value
                    print(f"ℹ️ Contenido alternativo detectado en clave '{key}' ({len(str(value))} caracteres)")
                    break
    
    def _extract_from_list(self, method_name: str, data: list):
        """Extrae datos útiles de una lista"""
        if not data:
            return
            
        # Si es lista de diccionarios
        if isinstance(data[0], dict):
            # Extraer IDs si existen
            if 'id' in data[0]:
                ids = [item['id'] for item in data if 'id' in item]
                self.data[f"{method_name}_ids"] = ids
                self.data[f"ids"] = ids
            
            # Almacenar lista completa
            self.data[f"{method_name}_list"] = data
        
        # Si es lista de strings/IDs
        elif isinstance(data[0], str):
            self.data[f"{method_name}_ids"] = data
    
    def _extract_from_string(self, method_name: str, data: str):
        """Extrae datos útiles de un string"""
        self.data[f"{method_name}_text"] = data
        self.data[f"last_text"] = data
    
    def resolve_parameter(self, param_name: str, param_type: str = None) -> Any:
        """Resuelve un parámetro basado en el contexto disponible"""
        
        # Búsqueda inteligente por nombre de parámetro
        resolution_strategies = [
            # Estrategia 1: Coincidencia exacta
            lambda: self.data.get(param_name),
            
            # Estrategia 2: Buscar IDs (con contador)
            lambda: self._resolve_id_parameter(param_name),
            
            # Estrategia 3: Buscar por tipo/patrón
            lambda: self._resolve_by_pattern(param_name),
            
            # Estrategia 4: Último resultado relevante
            lambda: self._resolve_last_relevant(param_name)
        ]
        
        for strategy in resolution_strategies:
            result = strategy()
            if result is not None:
                print(f"🎯 Parámetro '{param_name}' resuelto: {result}")
                return result
        
        print(f"❌ No se pudo resolver parámetro '{param_name}'")
        return None
    
    def _resolve_id_parameter(self, param_name: str):
        """Resuelve parámetros que terminan en '_id' con soporte para múltiples IDs"""
        if not param_name.endswith('_id'):
            return None
        
        # Extraer el prefijo (ej: 'file_id' -> 'file')
        prefix = param_name[:-3]
        
        # Buscar IDs relacionados
        possible_keys = [
            f"{prefix}_ids",
            f"{prefix}s_ids",  # plural
            "ids"
        ]
        
        for key in possible_keys:
            if key in self.data:
                ids = self.data[key]
                
                # 🔥 FIX: SIEMPRE usar contador para listas (sin importar la longitud)
                if isinstance(ids, list) and ids:
                    # Inicializar contador si no existe
                    if param_name not in self.resolution_counters:
                        self.resolution_counters[param_name] = 0
                    
                    # Obtener índice actual
                    index = self.resolution_counters[param_name]
                    
                    # Incrementar contador para la próxima llamada
                    self.resolution_counters[param_name] += 1
                    
                    # Retornar ID en la posición 'index'
                    if index < len(ids):
                        resolved_id = ids[index]
                        print(f"🔢 Usando ID en índice {index} de {len(ids)} disponibles")
                        return resolved_id
                    else:
                        # Si se agotaron los IDs, usar el último
                        print(f"⚠️ Índice {index} fuera de rango, usando último ID")
                        return ids[-1]
                
                # String: retornar directamente
                elif isinstance(ids, str):
                    return ids
        
        # Fallback: buscar last_id
        if "last_id" in self.data:
            return self.data["last_id"]
        
        return None
    
    def _resolve_by_pattern(self, param_name: str):
        """Resuelve por patrones comunes"""
        patterns = {
            'to': ['email', 'recipient', 'destination'],
            'subject': ['title', 'topic', 'asunto'],
            # 🔥 FIX: Priorizar contenido de archivos y LLM sobre mensajes de confirmación
            'body': [
                'drive.read_file_content',   # Prioridad 1: Contenido de archivos
                'llm.generate_content',      # Prioridad 2: Contenido generado por LLM
                'content',                   # Prioridad 3: Contenido genérico
                'text',                      # Prioridad 4: Texto
                'message',                   # Prioridad 5: Mensajes (confirmaciones)
                'description'                # Prioridad 6: Descripciones
            ],
            'content': ['body', 'text', 'message'],
            'query': ['search', 'term', 'keyword'],
            'max_results': [10, 5]
        }

        if param_name in patterns:
            for pattern in patterns[param_name]:
                if pattern in self.data:
                    return self.data[pattern]
                if isinstance(pattern, int):
                    return pattern
        
        return None
    
    def _resolve_last_relevant(self, param_name: str):
        """Resuelve usando el último resultado relevante"""
        fallback_keys = [
            f"last_{param_name}",
            f"{param_name}_result",
            "last_content",
            "last_text"
        ]
        
        for key in fallback_keys:
            if key in self.data:
                return self.data[key]
        
        return None
    
    def needs_content_generation(self, param_value: str) -> bool:
        """Verifica si un parámetro necesita generación de contenido"""
        if not param_value:
            return False
        
        generation_triggers = [
            "dynamic", "auto", "generate", 
            "dynamic_summary", "auto_summary",
            "generate_content", "create_content"
        ]
        
        return any(trigger in str(param_value).lower() for trigger in generation_triggers)
    
    async def generate_content_if_needed(self, param_name: str, param_value: str, user_input: str):
        """Genera contenido automáticamente si es necesario"""
        if not self.needs_content_generation(param_value):
            return param_value
        
        print(f"🤖 Generando contenido para parámetro '{param_name}'...")
        generated_content = await self._generate_contextual_content(param_name, user_input)
        
        if generated_content:
            print(f"✨ Contenido generado para '{param_name}' (longitud: {len(generated_content)})")
            return generated_content
        
        return param_value
    
    async def _generate_contextual_content(self, param_name: str, user_input: str) -> str:
        """Genera contenido usando el LLM"""
        
        if not hasattr(self, 'llm_service') or self.llm_service is None:
            print("❌ ERROR: El servicio LLM no está conectado a IntelligentContext.")
            return f"Error: LLM service not available for dynamic content generation of '{param_name}'."

        if param_name == 'body':
            prompt_instruction = (
                "Genera un cuerpo de texto profesional, completo y persuasivo "
                "basado en la siguiente solicitud del usuario. Tu respuesta debe ser "
                "SOLO el cuerpo del texto, sin introducción ni metadatos: "
            )
        elif param_name == 'subject':
            prompt_instruction = (
                "Genera un asunto de correo conciso, atractivo y profesional "
                "basado en la siguiente solicitud del usuario. Tu respuesta debe ser "
                "SOLO el asunto del texto, sin introducción ni metadatos: "
            )
        else:
            prompt_instruction = (
                f"Genera contenido para el parámetro '{param_name}' basado en el contexto. "
                "Tu respuesta debe ser SOLAMENTE el valor de contenido generado: "
            )
        
        full_prompt = f"{prompt_instruction}\n\n[SOLICITUD DEL USUARIO]: {user_input}"
        
        try:
            from apps.services.llm.llm_service import call_llm
            generated_content = await call_llm(full_prompt)
            return generated_content.strip()
        except Exception as e:
            print(f"❌ Error durante la generación LLM para '{param_name}': {e}")
            return f"Error al generar contenido LLM: {param_name}"