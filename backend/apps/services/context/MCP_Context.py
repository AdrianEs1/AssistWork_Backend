from typing import Any, List, Dict
import json
from apps.services.llm.llm_service import call_llm

class MCPContext:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.data: Dict[str, Any] = {"user_id": user_id}
        self.method_results: List[Dict] = []
        self.resolution_counters: Dict[str, int] = {}  # ← CLAVE

    def store_result(self, method_name: str, result: Any, step: int):
        self.method_results.append({
            "method": method_name,
            "result": result,
            "step": step
        })
        self.data[method_name] = result
        self.data["last_result"] = result
        
        # Análisis automático igual que IntelligentContext
        self._analyze_and_store_data(method_name, result)
        print(f"📦 Contexto actualizado por {method_name}")
        print(f"   Claves disponibles: {list(self.data.keys())}")

    def _analyze_and_store_data(self, method_name: str, result: Any):
        """Porta exacta de IntelligentContext — extrae IDs y contenido automáticamente."""

        print(f"🔍 [ANALYZE] method={method_name}")
        print(f"🔍 [ANALYZE] result type={type(result)}")
        print(f"🔍 [ANALYZE] result preview={str(result)[:300]}")
        
        actual_result = result
        if isinstance(result, list) and result:
            try:
                actual_result = json.loads(result[0])
                print(f"✅ [ANALYZE] JSON parseado correctamente, keys={list(actual_result.keys()) if isinstance(actual_result, dict) else type(actual_result)}")
            except Exception as e:
                print(f"❌ [ANALYZE] Error parseando JSON: {e}")
                actual_result = result
            
            # El resultado MCP llega como lista de strings JSON
            actual_result = result
            if isinstance(result, list) and result:
                try:
                    actual_result = json.loads(result[0])
                except Exception:
                    actual_result = result

        if isinstance(actual_result, dict):
            self._extract_from_dict(method_name, actual_result)
        elif isinstance(actual_result, list):
            self._extract_from_list(method_name, actual_result)
        elif isinstance(actual_result, str):
            self.data[f"{method_name}_text"] = actual_result
            self.data["last_text"] = actual_result

        # Acumular resultados
        results_key = f"{method_name}_results"
        if results_key not in self.data:
            self.data[results_key] = []
        self.data[results_key].append(actual_result)
        self.data[f"{method_name}_result"] = actual_result

    def _extract_from_dict(self, method_name: str, data: dict):
        for key, value in data.items():
            if isinstance(value, list) and value and isinstance(value[0], dict) and 'id' in value[0]:
                ids = [item['id'] for item in value if 'id' in item]
                
                # Acumular IDs
                for id_key in [f"{key}_ids", f"{method_name}_{key}_ids"]:
                    if id_key not in self.data:
                        self.data[id_key] = []
                    self.data[id_key].extend(ids)
                
                # Acumular objetos completos
                for data_key in [f"{key}_data", f"{method_name}_{key}_data"]:
                    if data_key not in self.data:
                        self.data[data_key] = []
                    self.data[data_key].extend(value)
                
                print(f"📝 IDs acumulados en '{key}_ids': {ids}")

            elif 'id' in key.lower():
                self.data[f"{method_name}_id"] = value
                self.data["last_id"] = value

        # Extraer content/body
        for key, value in data.items():
            if key.lower() in ['content', 'body', 'text', 'message']:
                contents_key = f"{method_name}_contents"
                if contents_key not in self.data:
                    self.data[contents_key] = []
                self.data[contents_key].append(value)
                self.data[f"{method_name}_content"] = value
                self.data["last_content"] = value
                break

    def _extract_from_list(self, method_name: str, data: list):
        if not data:
            return
        if isinstance(data[0], dict) and 'id' in data[0]:
            ids = [item['id'] for item in data if 'id' in item]
            self.data[f"{method_name}_ids"] = ids
            self.data["ids"] = ids
            self.data[f"{method_name}_list"] = data
        elif isinstance(data[0], str):
            self.data[f"{method_name}_ids"] = data

    def _resolve_id_parameter(self, param_name: str):
        """Porta exacta de IntelligentContext — contador secuencial para IDs."""
        if not param_name.endswith('_id'):
            return None

        prefix = param_name[:-3]  # 'message_id' → 'message'

        possible_keys = [
            f"{prefix}_ids",
            f"{prefix}s_ids",
            "emails_ids",   # fallback específico Gmail
            "ids"
        ]

        for key in possible_keys:
            if key in self.data:
                ids = self.data[key]
                if isinstance(ids, list) and ids:
                    if param_name not in self.resolution_counters:
                        self.resolution_counters[param_name] = 0

                    index = self.resolution_counters[param_name]
                    self.resolution_counters[param_name] += 1

                    if index < len(ids):
                        print(f"🔢 [{param_name}] Usando ID índice {index}/{len(ids)-1}: {ids[index]}")
                        return ids[index]
                    else:
                        print(f"⚠️ [{param_name}] Índice {index} agotado, usando último: {ids[-1]}")
                        return ids[-1]
                elif isinstance(ids, str):
                    return ids

        return self.data.get("last_id")

    def get_context_summary(self, max_chars: int = 3000) -> str:
        summary = ""
        for r in self.method_results:
            result_str = str(r.get("result", ""))
            summary += f"\n--- Paso {r['step']}: {r['method']} ---\n{result_str[:1000]}\n"
        return summary[:max_chars]

    async def resolve_dynamic_args(self, method_name: str, args: dict, user_input: str) -> dict:
        """
        Primero resuelve IDs con contador (determinístico),
        luego usa LLM solo para parámetros semánticos (body, subject, to, etc.)
        """
        dynamic_keys = [k for k, v in args.items() if v == "dynamic"]
        if not dynamic_keys:
            return args

        resolved = {}
        remaining = {}

        # PASO 1: IDs con contador — sin LLM
        for param_name in dynamic_keys:
            if param_name.endswith("_id"):
                id_value = self._resolve_id_parameter(param_name)
                if id_value is not None:
                    resolved[param_name] = id_value
                    print(f"✅ [{param_name}] resuelto por contador: {id_value}")
                else:
                    remaining[param_name] = "dynamic"
            else:
                remaining[param_name] = "dynamic"

        # PASO 2: Parámetros semánticos con LLM
        if remaining:
            context_snapshot = {
                k: v for k, v in self.data.items()
                if any(t in k.lower() for t in ["content", "text", "email", "subject", "body"])
            }

            prompt = f"""Eres un resolvedor de argumentos para un orquestador.

Método a ejecutar: {method_name}
Parámetros a resolver: {list(remaining.keys())}
Solicitud del usuario: {user_input}

Contexto disponible:
{json.dumps(context_snapshot, indent=2, ensure_ascii=False, default=str)[:2000]}

Devuelve SOLO un JSON con los valores resueltos.
Ejemplo: {{"to": "email@ejemplo.com", "subject": "Asunto", "body": "Contenido..."}}"""

            try:
                response = await call_llm(prompt)
                response = response.strip()
                if response.startswith("```"):
                    response = response.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                llm_resolved = json.loads(response)
                resolved.update(llm_resolved)
                print(f"✅ [LLM] Resuelto: {list(llm_resolved.keys())}")
            except Exception as e:
                print(f"⚠️ [LLM] Error resolviendo args semánticos: {e}")

        return {**args, **resolved}