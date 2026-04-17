import re
import inspect
import asyncio
from typing import Callable, Dict, Any, List, Optional
from functools import wraps

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}

    def tool(self, group: str, name: Optional[str] = None):
        """
        Decorador para registrar una función como herramienta.
        El nombre final será '{group}_{name_de_funcion}'.
        """
        def decorator(func: Callable):
            tool_name = name or func.__name__
            full_name = f"{group}_{tool_name}"
            
            # Extraer metadatos
            sig = inspect.signature(func)
            doc = func.__doc__ or f"Herramienta {tool_name}"
            
            # Guardar en el registro
            self.tools[full_name] = {
                "func": func,
                "group": group,
                "original_name": tool_name,
                "description": doc.strip(),
                "signature": sig,
                "parameters": self._generate_schema(sig, doc)
            }
            
            @wraps(func)
            async def wrapper(*args, **kwargs):
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return func(*args, **kwargs)
            
            return wrapper
        return decorator

    def _generate_schema(self, sig: inspect.Signature, doc: str) -> Dict[str, Any]:
        """Genera un JSON schema simplificado basado en la firma de la función y su docstring."""
        properties = {}
        required = []
        
        # Intentar extraer descripciones de parámetros del docstring (formato simple)
        param_descriptions = {}
        if doc:
            # Busca líneas como ":param nombre: descripción" o descriptores similares
            for line in doc.split('\n'):
                line = line.strip()
                if ':' in line and any(x in line.lower() for x in ['param', 'arg']):
                    parts = line.split(':', 2)
                    if len(parts) >= 2:
                        # Extraer el nombre del parámetro (segunda parte después de param/arg)
                        p_match = re.search(r'(?:param|arg)\s+([a-zA-Z_0-9]+)', parts[0], re.I)
                        if p_match:
                            p_name = p_match.group(1)
                            p_desc = parts[1].strip()
                            param_descriptions[p_name] = p_desc

        # Parámetros que inyectamos nosotros, el LLM no debe verlos
        INJECTED_PARAMS = {"user_id", "userId", "uid"}

        for name, param in sig.parameters.items():
            if name in INJECTED_PARAMS:
                continue
                
            # Determinar tipo
            p_type = "string"
            if param.annotation == int: p_type = "integer"
            elif param.annotation == float: p_type = "number"
            elif param.annotation == bool: p_type = "boolean"
            elif param.annotation == List or (hasattr(param.annotation, '__origin__') and param.annotation.__origin__ == list):
                p_type = "array"
            
            properties[name] = {
                "type": p_type,
                "description": param_descriptions.get(name, f"Parámetro {name}")
            }
            
            if param.default == inspect.Parameter.empty:
                required.append(name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required
        }

    def get_adk_tools(self, user_id: str) -> List[Callable]:
        """
        Retorna una lista de funciones preparadas para ser consumidas por Google ADK.
        Inyecta automáticamente el user_id en cada llamada.
        """
        adk_functions = []
        
        for full_name, info in self.tools.items():
            func = info["func"]
            sig = info["signature"]
            
            # Crear un wrapper para ADK que inyecte el user_id
            async def make_adk_wrapper(f_info, uid):
                original_func = f_info["func"]
                
                async def wrapper(**kwargs):
                    # Inyectar user_id si la función lo espera
                    if "user_id" in f_info["signature"].parameters:
                        kwargs["user_id"] = uid
                    
                    try:
                        if asyncio.iscoroutinefunction(original_func):
                            result = await original_func(**kwargs)
                        else:
                            result = await asyncio.to_thread(original_func, **kwargs)
                        
                        # Normalizar retorno para ADK (debe ser string o similar)
                        if isinstance(result, (dict, list)):
                            return str(result)
                        return result or "Operación completada"
                    except Exception as e:
                        return f"Error en {f_info['original_name']}: {str(e)}"

                # Preservar metadatos para ADK
                wrapper.__name__ = full_name
                wrapper.__doc__ = f_info["description"]
                
                # Ajustar firma para que el modelo no vea 'user_id'
                params = [
                    p for name, p in f_info["signature"].parameters.items() 
                    if name not in {"user_id", "userId", "uid"}
                ]
                wrapper.__signature__ = inspect.Signature(params)
                
                return wrapper

            # Usamos un factory async para el closure
            adk_functions.append(asyncio.run_coroutine_threadsafe(
                make_adk_wrapper(info, user_id), 
                asyncio.get_event_loop()
            ).result() if not asyncio.get_event_loop().is_running() else None)
            
        # Re-implementación simplificada para evitar problemas de bucles iniciados
        final_list = []
        for full_name, info in self.tools.items():
            final_list.append(self._create_adk_function(info, user_id))
            
        return final_list

    def _create_adk_function(self, info, user_id):
        """Helper sincrónico para crear la función compatible con ADK."""
        original_func = info["func"]
        full_name = info["original_name"] # Usamos original o prefixed? ADK usa func.__name__
        
        async def adk_wrapper(**kwargs):
            if "user_id" in info["signature"].parameters:
                kwargs["user_id"] = user_id
            
            if asyncio.iscoroutinefunction(original_func):
                return await original_func(**kwargs)
            else:
                return await asyncio.to_thread(original_func, **kwargs)

        adk_wrapper.__name__ = f"{info['group']}_{info['original_name']}"
        adk_wrapper.__doc__ = info["description"]
        
        # Firma sin user_id
        new_params = [
            p for name, p in info["signature"].parameters.items()
            if name not in {"user_id", "userId", "uid"}
        ]
        adk_wrapper.__signature__ = inspect.Signature(new_params)
        
        return adk_wrapper

TOOL_REGISTRY = ToolRegistry()
tool = TOOL_REGISTRY.tool
