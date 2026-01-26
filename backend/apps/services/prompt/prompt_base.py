"""
prompt_base.py
Base centralizada para la generación de prompts de planificación y selección
de métodos en herramientas multi-servicio (Drive, Gmail, etc.).
"""

import json
from typing import List, Dict, Union

# ======================================================
# 🌍 REGLAS GLOBALES COMPARTIDAS
# ======================================================

GLOBAL_RULES = """
    GENERAL RULES:
    - Always respond with a valid JSON object.
    - Never include Markdown, backticks, or commentary.
    - Do not invent or modify method names.
    - Only use arguments that appear in the provided signature.
    - Never include "user_id" unless explicitly mentioned.
    - All dynamic content placeholders should be written as "dynamic".
    - Keep the JSON clean, well-formatted, and minimal.

    DATA FLOW RULE:
    - Every method that requires content (like 'body' in email or 'content' in upload) 
      MUST be preceded by a data-gathering step (read_file, read_email, or action:llm).
    - You cannot use a 'dynamic' value if the source of that data has not been accessed 
      in a previous step of the SAME sequence.
      

    GENERAL RULES:
    - Return ONLY a valid JSON object, with no additional text.
    - Do NOT invent method names or parameters.
    - If the user requests content (email, summary, text), generate complete, natural language output.
    - Avoid including unsupported flags such as `html=True` or similar.
    - Do NOT use backticks or Markdown formatting.

    HARD CONSTRAINT LOCAL FILES:
    - For LocalFiles, read_file MUST NEVER be called unless list_files appears earlier in the SAME sequence.
    - Any plan that calls LocalFiles.read_file without a previous LocalFiles.list_files step is INVALID.
    - The path argument of read_file MUST come from the output of list_files.
    - File names provided by the user are NOT valid paths.

    AGENT QUERY RULE:
    - Values provided in agent-generated JSON fields like "query" represent logical identifiers.
    - Logical identifiers MUST be resolved via lookup (e.g. list_files) before being used as paths or ids.
    - Never pass a logical identifier directly to read_file.

    EMAIL AGGREGATION RULE:
    - If multiple recipient email addresses are obtained from a data source
      AND the email content (subject and body) is identical for all recipients,
      the agent MUST send a SINGLE email.
    - In this case, the "to" field MUST include all email addresses as a
      comma-separated list.
    - The agent MUST NOT generate multiple send_email calls when the content
      is the same for all recipients.
    - Multiple send_email calls are ONLY allowed if the content differs per recipient.

    """

# ======================================================
# 🧠 PLANTILLAS ESPECÍFICAS POR TIPO DE TAREA
# ======================================================

def get_prompt_template(task_type: str) -> str:
    """
    Devuelve la plantilla base según el tipo de tarea.
    """
    if task_type == "simple":
        return """
        You are selecting a SINGLE method that best satisfies the user's request.

        RULES:
        1. Select only ONE method from the available list.
        2. Only include valid parameters from the method signature.
        3. If the user asks for a count (e.g., "3 emails"), use that number.
        4. For email-type methods: valid params are to, subject, body.
        5. If HTML is mentioned, include actual <h1>, <p>, etc. tags.
        6. Use "dynamic" for values generated later by the system.
        7. Never use markdown, backticks, or explanations.

        EXAMPLES:
        ✅ "list my last 3 emails" → {{"method": "list_emails", "args": {{"max_results": 3}}}}
        ✅ "send email to juan@test.com" → {{"method": "send_email", "args": {{"to": "juan@test.com", "subject": "Hola", "body": "dynamic"}}}}
        ✅ "test connection" → {{"method": "test_connection", "args": {{}}}}

        Respond ONLY with valid JSON:
        {{"method": "selected_method", "args": {{"param": "value"}}}}
        """

    elif task_type == "complex":
      return """
        You are planning a COMPLEX task that may require reading, processing and then generating
        detailed content using an LLM. The output MUST be a valid JSON object (no markdown, no backticks).

        GUIDELINES:
        1. STRICT DEPENDENCY: If a task requires information NOT provided in the 'User request', 
        you MUST insert steps to fetch it. 
        - Need to summarize a file? Steps: list_files -> read_file -> action:llm.
        - Need to reply to an email? Steps: search_emails -> read_email -> action:llm -> send_email.
        2. Use only methods present in AVAILABLE METHODS. Do not invent method names or args.
        3. When you need file content, include a step with {"method": "read_file", "args": {"file_id": "<id|dynamic>"}}.
          If the plan discovers the file by name first, use list_files then read_file with file_id="dynamic".
        4. LLM ACTION AS A BRIDGE: 
        Use {"action": "llm", "task": "..."} as a bridge between FETCHING and ACTING. 
        The LLM action converts raw data (artifacts) into the final format needed for the next method.
        5. If the user requested a structured summary (e.g. "tema, resumen, recomendaciones"), instruct the LLM step to
          return the final content in that exact structure and language.
        6. Do NOT use "dynamic" for fields that must be produced by the LLM itself — instead, put those instructions into the "task".
        7. Always return JSON only. Do not add commentary or explanatory text.
        8. When searching files in Google Drive, ALWAYS use "name contains" instead of "name ="
           unless the user explicitly gives the full exact name including extension.
           Example: {"method": "list_files", "args": {"query": "name contains 'report'"}}.
        


        VALIDATION RULE:
        Before returning the JSON:
        - If read_file is present and the tool is LocalFiles,
          verify that list_files exists earlier in the sequence.
        - If not, the plan is invalid and MUST be corrected.

        EXAMPLE FLOWS (use these patterns when appropriate):

        — INVALID EXAMPLE (DO NOT DO THIS):

        { 
          "sequence": [
            {"method": "read_file", "args": {"path": "report"}}
          ]
        }

        — CORRECT EXAMPLE (LOCAL FILES REQUIRE DISCOVERY):
        {
          "sequence": [
            {"method": "list_files", "args": {"query": "name contains 'report'"}},
            {"method": "read_file", "args": {"path": "dynamic"}}
          ]
        }

        — If file name must be located then summarized:
        {
          "sequence": [
            {"method": "list_files", "args": {"query": "name contains 'acta_matricula'"}},
            {"method": "read_file", "args": {"file_id": "dynamic"}},
            {"action": "llm", "task": "Given the file content, produce a structured summary with sections: Tema, Resumen del contenido, Recomendaciones. Use Spanish."}
          ]
        }

        — If file_id is known:
        {
          "sequence": [
            {"method": "read_file", "args": {"file_id": "1A2b..."}},
            {"action": "llm", "task": "Summarize the provided content into: Tema, Resumen del contenido, Recomendaciones (in Spanish)."}
          ]
        }

        OUTPUT FORMAT REQUIRED:
        Return exactly one JSON object with key "sequence". Each element must be either:
        - a method call: {"method":"<name>", "args":{ ... }}
        - an LLM step: {"action":"llm", "task":"<clear generation instructions>"}

        Remember: NO backticks, NO markdown, ONLY valid JSON.
        """


    elif task_type == "multi_tool":
        
        return """
        You are planning a SEQUENCE of multiple method calls from this tool.

        RULES:
        1. Use only existing methods from the provided list.
        2. No invented method names or parameters.
        3. Use "dynamic" for values resolved later by context.
        4. You may include LLM tasks using {"action": "llm", "task": "specific description"}.
        5. Logical order: fetch data → process → act.
        6. Do not use markdown or backticks.
        7. Keep the sequence concise and goal-oriented.
        8. When generating Drive queries, prefer "name contains '<keyword>'" instead of "name = '<keyword>'" unless the user specifies the full filename with its extension.

        EXAMPLES:
        {{
          "sequence": [
            {{"method": "list_files", "args": {{"query": "type='pdf'"}}}},
            {{"action": "llm", "task": "summarize extracted files"}},
            {{"method": "upload_file", "args": {{"name": "summary.txt", "content": "dynamic"}}}}
          ]
        }}
        """

    else:
        return """
        Unknown task type. Defaulting to simple behavior.
        Respond with valid JSON only.
        {{"method": "default_action", "args": {{}}}}
        """


# ======================================================
# 🏗️ CONSTRUCTOR PRINCIPAL DEL PROMPT
# ======================================================

def build_prompt(tool_name: Union[str, List[str]], methods: List[Dict], user_input: str, task_type: str) -> str:
    """
    Construye dinámicamente el prompt completo para el modelo de lenguaje,
    soportando una o múltiples herramientas.
    """
    # 🔹 1️⃣ Normalizar herramienta(s)
    if isinstance(tool_name, list):
        tool_section = "Herramientas disponibles:\n" + "\n".join([f"- {t}" for t in tool_name])
    else:
        tool_section = f"Herramienta: {tool_name}"

    # 🔹 2️⃣ Convertir métodos a texto legible
    methods_info = json.dumps(methods, indent=2, ensure_ascii=False)

    # 🔹 3️⃣ Plantilla específica según tipo de tarea (simple / complex / multi_tool)
    template = get_prompt_template(task_type)

    # 🔹 4️⃣ Agregar instrucción especial si el tipo es multi_tool
    multi_tool_note = ""
    if task_type in ["complex", "multi_tool"]:
        multi_tool_note = """
        ⚙️ INSTRUCCIÓN ESPECIAL:
        - Puedes combinar métodos de distintas herramientas para resolver la petición del usuario.
        - Cada paso del plan debe incluir el campo `"tool"` con el nombre de la herramienta a usar.
        - Ejemplo de estructura válida:
          {
            "sequence": [
              {"tool": "gmail", "method": "list_emails", "args": {"label": "inbox"}},
              {"tool": "drive", "method": "upload_file", "args": {"file_path": "attachments.zip"}},
              {"action": "llm", "task": "summarize uploaded content"}
            ]
          }

          — RESOLVING FILE BY LOGICAL NAME (CRITICAL PATTERN):

        User input: "lee el archivo ClientesdelAgente"

        Correct plan:
        {
          "sequence": [
            {
              "method": "list_files",
              "args": {
                "query": "name contains 'ClientesdelAgente'"
              }
            },
            {
              "method": "read_file",
              "args": {
                "path": "dynamic"
              }
            }
          ]
        }

        — SENDING SAME EMAIL TO MULTIPLE RECIPIENTS:

        {
          "sequence": [
            {
              "method": "list_files",
              "args": { "query": "name contains 'ClientesOptimusAgent'" }
            },
            {
              "method": "read_file",
              "args": { "path": "dynamic" }
            },
            {
              "method": "list_files",
              "args": { "query": "name contains 'InvitacionOptimusAgent'" }
            },
            {
              "method": "read_file",
              "args": { "path": "dynamic" }
            },
            {
              "method": "send_email",
              "args": {
                "to": "correoA@gmail.com, correoB@gmail.com",
                "subject": "Invitación Optimus",
                "body": "dynamic"
              }
            }
          ]
        }


        Explanation:
        - "ClientesdelAgente" is NOT a path.
        - list_files resolves the logical name to a concrete path.
        - read_file MUST use the resolved path, never the original name.

        
        verification_instruction = 
        === FINAL VALIDATION CHECK ===
        Before returning the JSON, verify:
        1. Does Step N+1 depend on data from Step N? If so, is Step N a 'read' or 'list' method?
        2. If I'm sending or uploading something 'dynamic', did I include a step to 'read' the source?
        3. Is every 'file_id' or 'message_id' either explicit or marked as 'dynamic' after a search step?
      
        """

    # 🔹 5️⃣ Prompt final unificado
    return f"""
    === CONTEXTO ===
    {tool_section}
    User request: "{user_input}"

    === MÉTODOS DISPONIBLES ===
    {methods_info}

    === REGLAS GLOBALES ===
    {GLOBAL_RULES}

    === INSTRUCCIONES ESPECÍFICAS ({task_type.upper()}) ===
    {template}
    {multi_tool_note}

    Responde ÚNICAMENTE con un objeto JSON válido siguiendo la estructura anterior.
    """



def get_decision_prompt(user_input: str, context: str, available_tools: list) -> str:
    """
    Clasificador de intención refinado y agnóstico.
    Detecta el tipo de tarea y las herramientas estrictamente necesarias
    basándose en las descripciones de las herramientas disponibles.
    """

    # 🔹 Normalizar available_tools (soporta strings o dicts)
    if available_tools and isinstance(available_tools[0], str):
        # Si llegan como strings, convertirlos a formato dict
        tools_list = [{"name": tool, "description": f"Handles {tool}-related operations"} 
                      for tool in available_tools]
    else:
        # Ya vienen como dicts con name y description
        tools_list = available_tools

    # Construir información dinámica de herramientas
    tools_description = "\n".join([
        f"- {tool['name']}: {tool.get('description', 'No description available')}"
        for tool in tools_list
    ]) if tools_list else "No tools available"

    return f"""
      SYSTEM ROLE:
      You are an intelligent orchestrator that classifies user requests based on intent and available tools.

      USER INPUT:
      "{user_input}"

      CONTEXT:
      {context}

      AVAILABLE TOOLS AND THEIR CAPABILITIES:
      {tools_description}

      === TASK TYPES ===
      🟢 simple → One direct action using a single method from one tool.
      🟡 complex → One reasoning or creative task that generates new content (LLM).
      🔵 multi_tool → Sequential actions involving DIFFERENT tools or multiple stages of reasoning.
      🟣 agent_help → User asking about agent capabilities, how to use it, or needs guidance.
      ⚪ conversation → General chat not requiring tools.

      === DECISION LOGIC (STRICT & AGNOSTIC) ===
      
      1️⃣ **Analyze the user request semantically**:
         - Identify the PRIMARY action requested (read, list, send, delete, create, analyze, etc.)
         - Identify the PRIMARY resource mentioned (file, email, document, folder, message, etc.)
         - Identify any SECONDARY actions (e.g., "find X and then send it via Y")

      2️⃣ **Match resources to tools**:
         - For EACH resource/action mentioned, determine which available tool handles it.
         - Use the tool descriptions to make this determination.
         - ONLY include a tool if the request explicitly requires its functionality.
         - DO NOT include a tool if:
           * The resource it handles is not mentioned in the request
           * The action it provides is not needed for the request
           * It's only vaguely related but not directly required

      3️⃣ **Determine task type**:
         - **simple**: One direct action using one tool (e.g., "list my files", "read email")
         - **complex**: Requires content generation/transformation with LLM (e.g., "summarize", "explain", "write")
         - **multi_tool**: Either:
           a) Uses multiple DIFFERENT tools (e.g., "read file and email it")
           b) Uses ONE tool in a sequence with LLM (e.g., "find file and summarize it")
         - **conversation**: General chat, no tools needed

      4️⃣ **Verification step** (CRITICAL):
         Before finalizing your response, ask yourself for EACH tool you're including:
         - "Is this tool's functionality EXPLICITLY required by the user's request?"
         - "Does the request mention a resource that ONLY this tool can handle?"
         - If the answer to BOTH questions is NO → REMOVE that tool from the list.

      === RESPONSE FORMAT (STRICT JSON) ===

      Return ONE of these formats based on the request:

      Case A - Single tool needed (MOST COMMON):
      {{
        "actions": ["tool_name"],
        "type": "simple" or "multi_tool"
      }}

      Case B - Multiple tools needed (RARE):
      {{
        "actions": ["tool_1", "tool_2"],
        "type": "multi_tool"
      }}

      Case C - No tools needed:
      {{
        "actions": [],
        "type": "conversation"
      }}

      === REASONING EXAMPLES (TOOL-AGNOSTIC) ===

      Example 1: "summarize the report.pdf file"
      Analysis:
      - PRIMARY action: summarize (requires LLM)
      - PRIMARY resource: file/document
      - Tool needed: whichever tool handles files (e.g., "drive")
      - NO other tools mentioned or implied
      Result: {{"actions": ["drive"], "type": "multi_tool"}}

      Example 2: "list my recent messages"
      Analysis:
      - PRIMARY action: list
      - PRIMARY resource: messages/emails
      - Tool needed: whichever tool handles messages (e.g., "gmail")
      - NO other tools mentioned or implied
      Result: {{"actions": ["gmail"], "type": "simple"}}

      Example 3: "find the budget file and send it to john@example.com"
      Analysis:
      - PRIMARY action: find (file) + send (email)
      - PRIMARY resources: file AND email
      - Tools needed: file handler (e.g., "drive") + email handler (e.g., "gmail")
      - BOTH tools are explicitly required
      Result: {{"actions": ["drive", "gmail"], "type": "multi_tool"}}

      Example 4: "read the document named 'proposal'"
      Analysis:
      - PRIMARY action: read
      - PRIMARY resource: document/file
      - Tool needed: whichever tool handles documents (e.g., "drive")
      - NO email, NO sending, NO other tools implied
      Result: {{"actions": ["drive"], "type": "simple"}}

      Example 5: "hello, how are you?"
      Analysis:
      - No specific action or resource mentioned
      - General conversation
      Result: {{"actions": [], "type": "conversation"}}

      === AGENT_HELP EXAMPLES (CRITICAL) ===

      📚 **Questions about agent capabilities:**
      "¿Qué puedes hacer?" → {{"actions": [], "type": "agent_help"}}
      "Cuáles son tus funciones" → {{"actions": [], "type": "agent_help"}}
      "Para qué sirves" → {{"actions": [], "type": "agent_help"}}
      "Qué habilidades tienes" → {{"actions": [], "type": "agent_help"}}

      🔗 **Questions about connecting/OAuth:**
      "Cómo conecto Gmail" → {{"actions": [], "type": "agent_help"}}
      "Cómo conectar mis aplicaciones" → {{"actions": [], "type": "agent_help"}}
      "Cómo conectar Drive" → {{"actions": [], "type": "agent_help"}}
      "No sé cómo conectar mi cuenta" → {{"actions": [], "type": "agent_help"}}
      "Qué permisos necesitas" → {{"actions": [], "type": "agent_help"}}

      🆘 **Help/confusion:**
      "Ayuda, estoy perdido" → {{"actions": [], "type": "agent_help"}}
      "No sé cómo empezar" → {{"actions": [], "type": "agent_help"}}
      "No entiendo cómo usarte" → {{"actions": [], "type": "agent_help"}}
      "Tengo problemas" → {{"actions": [], "type": "agent_help"}}

      === CRITICAL DISTINCTIONS ===

      ⚠️ **IMPORTANT: Differentiate questions ABOUT the agent vs actions WITH tools**

      ❌ WRONG:
      "Cómo conectar Gmail" → {{"actions": ["gmail"], "type": "simple"}}
      Reason: User does NOT want to USE Gmail, wants to know HOW to connect it

      ✅ CORRECT:
      "Cómo conectar Gmail" → {{"actions": [], "type": "agent_help"}}
      Reason: Question about the agent's connection process

      ❌ WRONG:
      "Qué puedes hacer con Drive" → {{"actions": ["drive"], "type": "simple"}}
      Reason: Question about capabilities, not an action

      ✅ CORRECT:
      "Qué puedes hacer con Drive" → {{"actions": [], "type": "agent_help"}}
      Reason: Question about agent functionality

      🔑 **KEY RULE:**
      If the question includes phrases like:
      - "how to connect", "how to use", "what is it for"
      - "what can you do", "what are your functions"
      - "help", "I don't know", "I don't understand"
      - "cómo conectar", "cómo usar", "para qué sirve"
      - "qué puedes hacer", "ayuda", "no sé"

      → It's **agent_help**, NOT a tool action

      === CRITICAL REMINDERS ===
      ⚠️ BE STRICT: Only include tools whose functionality is DIRECTLY required.
      ⚠️ DO NOT assume: If a tool isn't explicitly needed, don't include it.
      ⚠️ One resource = One tool: Unless the request mentions multiple distinct resources/actions.
      ⚠️ Output ONLY valid JSON. No markdown, no backticks, no commentary.
      """



# ======================================================
# ✅ EJEMPLO DE USO
# ======================================================
if __name__ == "__main__":
    test_prompt = build_prompt(
        tool_name="drive",
        methods=[
            {"name": "list_files", "signature": "(query: str = None, max_results: int = 10)", "description": "List Google Drive files"},
            {"name": "read_file", "signature": "(file_id: str)", "description": "Read content of a Drive file"},
            {"name": "upload_file", "signature": "(name: str, content: str)", "description": "Upload a file to Drive"},
        ],
        user_input="resume el archivo acta_matricula",
        task_type="multi_tool"
    )

    print(test_prompt)
