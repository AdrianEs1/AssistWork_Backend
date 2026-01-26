from typing import List, Dict
import json
from apps.services.llm.small_llm_service import call_small_llm
from apps.services.llm.llm_service import call_llm
from apps.services.prompt.prompt_base import build_prompt


async def select_simple_method(tool_name: str, methods: List[Dict], user_input: str):
    """Selecciona método simple usando Groq con mejor lógica"""
    

    planning_prompt = build_prompt(tool_name, methods, user_input, task_type="simple")

    
    try:
        selection_text = await call_llm(planning_prompt)
        print(f"🎯 Selección de Gemini(simple_method): {selection_text}")
        
        # Limpiar respuesta si viene con markdown
        if selection_text.strip().startswith('```'):
            lines = selection_text.strip().split('\n')
            json_lines = []
            in_json = False
            for line in lines:
                if line.strip().startswith('```') and 'json' in line.lower():
                    in_json = True
                    continue
                elif line.strip() == '```':
                    in_json = False
                    continue
                elif in_json:
                    json_lines.append(line)
            selection_text = '\n'.join(json_lines)
        
        selection_data = json.loads(selection_text.strip())
        
        # Validar que el método seleccionado existe
        valid_method_names = {method['name'] for method in methods}
        selected_method = selection_data.get("method")
        
        if selected_method not in valid_method_names:
            print(f"❌ ERROR: Método '{selected_method}' no existe en {tool_name}")
            print(f"   Métodos válidos: {list(valid_method_names)}")
            return {"error": f"Método '{selected_method}' no válido. Métodos disponibles: {list(valid_method_names)}"}
        
        # Validar estructura
        if "method" not in selection_data or "args" not in selection_data:
            return {"error": f"Respuesta mal formateada: {selection_text}"}
        
        # Filtrar argumentos inválidos que puedan causar problemas de parsing
        args = selection_data.get("args", {})
        filtered_args = {}
        
        for key, value in args.items():
            # Filtrar parámetros problemáticos específicos
            if key == "html" and selected_method == "send_email":
                # El método send_email no acepta "html", usa content_type
                if value:
                    filtered_args["content_type"] = "text/html"
                continue
            else:
                filtered_args[key] = value
        
        selection_data["args"] = filtered_args
        print(f"🔧 Argumentos filtrados: {filtered_args}")
            
        return selection_data
        
    except json.JSONDecodeError as e:
        print(f"❌ Error parseando selección: {selection_text}")
        print(f"❌ Error JSON: {e}")
        return {"error": f"Respuesta JSON inválida: {selection_text}"}
    
    except Exception as e:
        print(f"❌ Error en select_simple_method: {e}")
        return {"error": f"Error inesperado: {str(e)}"}