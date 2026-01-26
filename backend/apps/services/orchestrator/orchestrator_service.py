import json
import inspect
from typing import List, Dict, Any, Optional, Union, Callable, Awaitable
from apps.services.llm.small_llm_service import call_small_llm
from apps.services.llm.llm_service import call_llm
from apps.services.tool_register.tool_registry import TOOL_REGISTRY
from apps.services.context.intelligent_context import IntelligentContext
from apps.services.flows.execute_simple_flow import select_simple_method
from apps.services.flows.execute_complex_flow import plan_method_sequence, execute_method_sequence
from apps.services.utils.utils import get_function_signature
from apps.services.prompt.prompt_base import get_decision_prompt
import textwrap


async def evolved_self_reflection(tool_name: str, user_input: str) -> dict:
    """Self-reflection evolucionado que descubre métodos de la tool"""
    
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return {"error": f"Tool '{tool_name}' no encontrada"}
    
    if not isinstance(tool, dict):
        # Tool simple (función directa)
        return {
            "methods": [{
                "name": tool_name,
                "signature": get_function_signature(tool),
                "description": "Herramienta simple"
            }]
        }
    
    # Tool compleja (múltiples métodos)
    methods = []
    for method_name, method_data in tool.items():
        func = method_data.get("func")
        if func:
            methods.append({
                "name": method_name,
                "signature": get_function_signature(func),
                "description": method_data.get("description", "")
            })
    
    return {"methods": methods}




async def generate_final_content_if_needed(context: IntelligentContext, user_input: str, results: List[Dict]) -> Optional[str]:
    """Genera contenido final basado en el contexto si es necesario - DEPRECATED"""
    # Esta función ya no es necesaria porque la generación se hace en tiempo real
    return None



## ESTA PARTE SE MANTIEN AQUÍ EN ESTE MÓDULO

# Definir tipo de callback
EventCallback = Optional[Callable[[str, dict], Awaitable[None]]]

async def orchestrator(user_input: str, user_id: str = None, context: str = "", event_callback: EventCallback = None) -> dict:
    """Orquestador genérico y escalable"""
    
    # === 1. Decisión inicial con G ===
    available_tools = TOOL_REGISTRY.list_tools()
    print(f"🔧 Herramientas disponibles: {available_tools}")
    
    decision_prompt = get_decision_prompt(user_input, context, available_tools)


    decision_text = await call_llm(decision_prompt)
    print(f"🤖 Decisión de Gemini en Clasificación de accion: {decision_text}")

    # Emitir evento: Analizando
    if event_callback:
        await event_callback("analyzing", {
            "message": "Analizando tu petición..."
        })

    try:
        decision = json.loads(decision_text)
    except json.JSONDecodeError:
        return {
            "success": False,
            "message": None,
            "error": f"[ORCH] Decisión inválida de Gemini: {decision_text}"
        }

    actions = decision.get("actions", [])
    task_type = decision.get("type", "simple")

    from apps.services.prompt.agent_identity import (
        AGENT_IDENTITY, 
        OAUTH_GUIDE, 
        TROUBLESHOOTING_GUIDE,
        QUICK_START_GUIDE
    )

    # === 2. Manejar ayuda del agente ===
    if task_type == "agent_help":
        help_prompt = f"""
        {AGENT_IDENTITY}
        
        {OAUTH_GUIDE}
        
        {TROUBLESHOOTING_GUIDE}
        
        {QUICK_START_GUIDE}
        
        INSTRUCCIONES:
        El usuario pregunta: "{user_input}"
        Contexto adicional: {context}
        
        Analiza la pregunta y responde de manera apropiada:
        
        - Si pregunta sobre **capacidades/funciones**: Explica brevemente qué puedes hacer con ejemplos concretos
        - Si pregunta sobre **cómo conectar apps**: Da la guía paso a paso de OAuth
        - Si necesita **ayuda para empezar**: Ofrece la guía rápida y ejemplos simples
        - Si tiene **problemas técnicos**: Guía con el troubleshooting básico
        - Si pregunta algo **mixto**: Combina las secciones relevantes
        
        FORMATO DE RESPUESTA:
        - Usa **negritas** para resaltar puntos importantes
        - Usa emojis para mejor legibilidad (pero no abuses)
        - Sé conciso pero completo
        - Estructura en secciones si es necesario
        - Termina invitando al usuario a probar algo específico
        
        Sé amigable, claro y motivador. Tu objetivo es que el usuario se sienta seguro para usar el agente.
        """
        
        response = await call_llm(help_prompt)
        
        return {
            "success": True,
            "message": response,
            "data": {"type": "agent_help"},
            "error": None
        }

    # === 2. Manejar conversación general ===
    if task_type == "conversation":
        conversation_prompt = f"""
        El usuario ha dicho: "{user_input}"
        Contexto: {context}

        Responde de manera natural y conversacional.
        NO utilices formatos HTML O JSON
        No utilices backticks
        """
        response = await call_llm(conversation_prompt)
        
        return {
            "success": True,
            "message": response,
            "data": {"tools_used": []},
            "error": None
        }

    # === 3. Manejar herramientas ===
    # ✅ Validar que las herramientas detectadas existen
    missing = [t for t in actions if t not in available_tools]
    if missing:
        return {
            "success": False,
            "message": None,
            "error": f"[ORCH] Herramientas no disponibles: {missing}"
        }
    

    # === 4. Detección proactiva: Herramientas requeridas pero no conectadas ===
    if actions and user_id:
        disconnected_tools = []
        
        for tool_name in actions:
            if tool_name in ["gmail", "drive"]:  # Solo herramientas OAuth
                try:
                    # Obtener la herramienta del registry
                    tool = TOOL_REGISTRY.get(tool_name)
                    if tool and "test_connection" in tool:
                        # Ejecutar test_connection
                        test_func = tool["test_connection"]["func"]
                        result = test_func(user_id=user_id)
                        
                        # Si falla, la herramienta no está conectada
                        if not result.get("success", False):
                            disconnected_tools.append(tool_name)
                except Exception as e:
                    # Si hay cualquier error, asumir que no está conectada
                    print(f"⚠️ Error verificando {tool_name}: {e}")
                    disconnected_tools.append(tool_name)
        
        # Si hay herramientas desconectadas, responder proactivamente
        if disconnected_tools:
            tools_list = " y ".join([f"**{t.capitalize()}**" for t in disconnected_tools])
            tools_simple = ", ".join(disconnected_tools)
            
            guide_message =f"""⚠️ **Necesito acceso a** {tools_list}\n
Para ejecutar tu petición: \n
{user_input[:60]}{'...' if len(user_input) > 60 else ''}\n
Primero necesitas conectar {tools_list}.\n\n
📍 **Cómo hacerlo:**\n
- Ve al menú Apps (esquina superior derecha)
- Busca {tools_list}
- Haz clic en Conectar
- Autoriza los permisos en la ventana de Google
- Vuelve e intenta tu comando de nuevo
"""
            
            return {
                "success": False,
                "message": guide_message,
                "data": {"missing_tools": disconnected_tools, "type": "oauth_required"},
                "error": "tools_not_connected"
            }



    # === 4. Self-reflection evolucionado ===
    
    all_methods = []

    # --- NUEVA LÓGICA DE VALIDACIÓN ---
    # Si no hay acciones, se saltan las llamadas a evolved_self_reflection.
    # Esto ocurre cuando task_type es 'complex' o 'conversation'.
    if not actions:
        print("🔍 No hay acciones requeridas. Saltando Self-reflection.")
        # Si no hay acciones, 'all_methods' queda vacío (lo cual es correcto)
        
    # --- LÓGICA EXISTENTE PARA MÚLTIPLES ACCIONES ---
    elif isinstance(actions, list) and len(actions) > 1:
        print(f"🔍 Reflexión múltiple: {actions}")
        for tool in actions:
            reflection_result = await evolved_self_reflection(tool, user_input)
            
            # ... (código para manejar errores y agregar métodos) ...
            if "error" in reflection_result:
                return {
                    "success": False,
                    "message": None,
                    "error": f"[ORCH] {reflection_result['error']}"
                }
            for m in reflection_result["methods"]:
                m["tool"] = tool
                all_methods.append(m)

    # --- LÓGICA EXISTENTE PARA UNA SOLA ACCIÓN ---
    # Entra aquí si 'actions' NO está vacío y no tiene más de 1 elemento (len == 1)
    else:
        # Se asegura de obtener la acción, sea una lista con un elemento o un string (por seguridad)
        action = actions[0] if isinstance(actions, list) and actions else actions
        
        # ⚠️ Nota: 'actions' en este punto debe ser seguro que tiene al menos un elemento,
        # ya que el caso de lista vacía se manejó arriba con 'if not actions:'
        
        reflection_result = await evolved_self_reflection(action, user_input)
        
        # ... (código para manejar errores y agregar métodos) ...
        if "error" in reflection_result:
            return {
                "success": False,
                "message": None,
                "error": f"[ORCH] {reflection_result['error']}"
            }
        for m in reflection_result["methods"]:
            m["tool"] = action
            all_methods.append(m)

    methods = all_methods
    # Nota: Si actions fue [], methods será [] y el orquestador continuará.
    print(f"📋 Métodos combinados: {[m['name'] for m in methods]}")


    # === 5. Planificación/Selección según tipo de tarea ===
    intelligent_context = IntelligentContext()
    
    action = actions[0] if actions else None

    if task_type == "simple":
        # Groq selecciona método simple
        selection = await select_simple_method(action, methods, user_input)
        
        if "error" in selection:
            return {
                "success": False,
                "message": None,
                "error": f"[ORCH] Error en selección simple: {selection['error']}"
            }
        
        sequence = [selection]
        
    elif task_type in ["complex", "multi_tool"]:
    # ✅ Adaptar para soportar una o varias herramientas
        
        sequence = await plan_method_sequence(action, methods, user_input, task_type)
        
        if not sequence:
            return {
                "success": False,
                "message": None,
                "error": "[ORCH] No se pudo generar secuencia de métodos"
            }
        
        # Emitir evento: Planificación
        if event_callback:
            total_steps = len(sequence)
            method_names = []
            for step in sequence:
                if "method" in step:
                    method_names.append(step["method"])
                elif step.get("action") == "llm":
                    method_names.append("llm_processing")
            
            await event_callback("planning", {
                "message": f"Planificando secuencia de {total_steps} pasos...",
                "steps": method_names,
                "total": total_steps
            })



    # === 6. Ejecución con contexto inteligente ===
    intelligent_context = IntelligentContext()
    if user_id:
        intelligent_context.data["user_id"] = user_id  #
        print(f"🔑 user_id guardado en contexto: {user_id}")  # ← Agregar esto
    else:
        print("⚠️ user_id NO recibido en orchestrator")  # ← Y esto

    intelligent_context.reset_resolution_counters()

    execution_result = await execute_method_sequence(actions, sequence, user_input, intelligent_context, event_callback=event_callback)
    
    if not execution_result["success"]:
        return {
            "success": False,
            "message": None,
            "error": f"[ORCH] Error en ejecución: {execution_result.get('error', 'Error desconocido')}",
            "data": {"results": execution_result.get("results", [])}
        }

    # === 7. Resultado final ===
    results = execution_result["results"]
    successful_methods = []
    for r in results:
        if r.get("success", False):
            if "method" in r:
                successful_methods.append(r["method"])
            elif r.get("type") == "llm":
                successful_methods.append("llm_processing")
            elif r.get("type") == "iteration":
                successful_methods.append(f"{r.get('method', 'unknown')}_iteration")
            else:
                successful_methods.append("unknown_step")

    # Obtener el mensaje user-friendly del último método ejecutado
    response_message = "Operación completada"  # Mensaje por defecto


    if results:
        # Obtener el último resultado exitoso
        last_successful_result = None
        for result in reversed(results):
            if result.get("success", False):
                last_successful_result = result
                break

        if last_successful_result:
            # 🔥 FIX 1: Determinar la clave correcta según el tipo de paso
            if last_successful_result.get("type") == "llm":
                # Para pasos LLM, buscar en llm.generate_content (nuevo formato)
                method_name = "llm_processing"
                
                # 🔥 OPCIÓN A: Buscar el contenido del último LLM
                context_key = "llm.generate_content"  # ← Último contenido LLM
                
                # 🔥 OPCIÓN B (alternativa): Obtener desde el resultado directamente
                # response_message = last_successful_result.get("result", "")
                
            elif "method" in last_successful_result:
                # Paso de método normal
                method_name = last_successful_result["method"]
                tool_name = last_successful_result.get("tool")
                
                if tool_name:
                    context_key = f"{tool_name}.{method_name}_result"
                else:
                    context_key = f"{method_name}_result"
                    
            elif last_successful_result.get("type") == "iteration":
                # Paso de iteración
                method_name = f"{last_successful_result.get('method', 'unknown')}_iteration"
                context_key = f"{last_successful_result.get('method', 'unknown')}_iteration_results"
            else:
                # Fallback
                method_name = "unknown_step"
                context_key = "last_content"
            
            # 🔥 FIX 2: Obtener el mensaje sin truncar ni añadir texto extra
            if context_key in intelligent_context.data:
                method_result = intelligent_context.data[context_key]
                
                # Si es dict con 'message' (resultado de método)
                if isinstance(method_result, dict):
                    if "message" in method_result:
                        response_message = method_result["message"]
                    elif "content" in method_result:
                        # Si es dict con 'content' (formato de llm.generate)
                        response_message = method_result["content"]
                    else:
                        response_message = str(method_result)
                
                # Si es string (contenido directo)
                elif isinstance(method_result, str):
                    # 🔥 FIX 3: NO truncar, pasar el contenido COMPLETO
                    response_message = method_result
                
                else:
                    response_message = f"✅ Ejecutado {method_name} correctamente"
            else:
                # Si no se encuentra la clave, fallback
                response_message = f"✅ Ejecutado {method_name} correctamente"

    """# Para secuencias multi-tool, agregar info de la secuencia
    successful_methods = []
    for r in results:
        if r.get("success", False):
            if "method" in r:
                successful_methods.append(r["method"])
            elif r.get("type") == "llm":
                successful_methods.append("llm_processing")
            elif r.get("type") == "iteration":
                successful_methods.append(f"{r.get('method', 'unknown')}_iteration")

    if len(successful_methods) > 1:
        sequence_info = f"\n\n📊 **Secuencia completada:** {' → '.join(successful_methods)}"
        response_message += sequence_info"""

    # Emitir evento: Guardando
    if event_callback:
        await event_callback("saving", {
            "message": "Guardando resultados..."
        })

    return {
        "success": True,
        "message": response_message,  # ← Contenido COMPLETO sin truncar
        "data": {
            "tool_used": actions,
            "methods_executed": successful_methods,
            "total_steps": len(results),
            "context_keys": list(intelligent_context.data.keys())
        },
        "error": None
    }