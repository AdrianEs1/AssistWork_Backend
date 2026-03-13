"""
prompt_base.py
Base centralizada para la generación de prompts de planificación y selección
de métodos en herramientas multi-servicio (Drive, Gmail, etc.).
"""

import json
from typing import List, Dict, Union

GLOBAL_RULES = """
    GENERAL RULES:
    - Always respond with a valid JSON object with key "sequence".
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

    HARD CONSTRAINT LOCAL FILES:
    - For LocalFiles, read_file MUST NEVER be called unless list_files appears earlier in the SAME sequence.
    - Any plan that calls LocalFiles.read_file without a previous LocalFiles.list_files step is INVALID.
    - The path argument of read_file MUST come from the output of list_files.
    - File names provided by the user are NOT valid paths.

    AGENT QUERY RULE:
    - Logical identifiers MUST be resolved via lookup (e.g. list_files) before being used as paths or ids.
    - Never pass a logical identifier directly to read_file.

    EMAIL AGGREGATION RULE:
    - If multiple recipient email addresses are obtained from a data source
      AND the email content is identical for all recipients,
      send a SINGLE email with all addresses as a comma-separated list in "to".
    - Multiple send_email calls are ONLY allowed if the content differs per recipient.
"""


def get_prompt_template(task_type: str) -> str:
    if task_type in ["complex", "multi_tool", "simple"]:
        return """
        You are planning a sequence of method calls to fulfill the user's request.
        The sequence can be as short as ONE step or as long as needed.

        GUIDELINES:
        1. MINIMUM STEPS: Use the fewest steps necessary.
           - If the request requires only ONE method call, return a sequence with ONE step.
           - Only add steps when they are strictly required by the data flow.

        2. STRICT DEPENDENCY: If a task requires information not provided in the request,
           insert steps to fetch it first.
           - Need to summarize a file? → list_files → read_file → action:llm
           - Need to reply to an email? → search_emails → read_email → action:llm → send_email
           - Just listing emails? → list_emails (ONE step, no more)

        3. LLM ACTION AS A BRIDGE:
           Use {"action": "llm", "task": "..."} to convert raw data into the final format.
           Only add an LLM step when content generation or transformation is required.

        4. Use only methods present in AVAILABLE METHODS. Do not invent method names or args.

        5. Use "dynamic" for values resolved from previous steps.
           Never use "dynamic" if the source data has not been fetched in a prior step.

        6. When searching files in Google Drive, ALWAYS use "name contains 'keyword'"
           unless the user provides the full exact filename with extension.

        7. Each step must include "tool" field when multiple tools are available.

        8. Always return JSON only. No commentary, no backticks, no markdown.

        EXAMPLES:

        — ONE STEP (direct action, no dependencies):
        User: "list my last 5 emails"
        {
          "sequence": [
            {"tool": "gmail", "method": "list_emails", "args": {"max_results": 5}}
          ]
        }

        — ONE STEP (direct send):
        User: "send email to juan@test.com saying hello"
        {
          "sequence": [
            {"tool": "gmail", "method": "send_email", "args": {"to": "juan@test.com", "subject": "Hola", "body": "Hola, ¿cómo estás?"}}
          ]
        }

        — TWO STEPS (fetch + LLM):
        User: "summarize my last email"
        {
          "sequence": [
            {"tool": "gmail", "method": "list_emails", "args": {"max_results": 1}},
            {"tool": "gmail", "method": "read_email", "args": {"message_id": "dynamic"}},
            {"action": "llm", "task": "Summarize the email content clearly and concisely."}
          ]
        }

        — MULTI STEP (read file and email it):
        User: "find the proposal file and send it to john@example.com"
        {
          "sequence": [
            {"tool": "drive", "method": "list_files", "args": {"query": "name contains 'proposal'"}},
            {"tool": "drive", "method": "read_file", "args": {"file_id": "dynamic"}},
            {"action": "llm", "task": "Prepare the email body with the file content."},
            {"tool": "gmail", "method": "send_email", "args": {"to": "john@example.com", "subject": "Proposal", "body": "dynamic"}}
          ]
        }

        — READ MULTIPLE EMAILS:
        User: "read my last 3 emails and summarize them"
        {
          "sequence": [
            {"tool": "gmail", "method": "list_emails", "args": {"max_results": 3}},
            {"tool": "gmail", "method": "read_email", "args": {"message_id": "dynamic"}},
            {"tool": "gmail", "method": "read_email", "args": {"message_id": "dynamic"}},
            {"tool": "gmail", "method": "read_email", "args": {"message_id": "dynamic"}},
            {"action": "llm", "task": "Summarize all three emails with sender, subject and importance level."}
          ]
        }

        FINAL VALIDATION (check before returning):
        1. Does every step that uses "dynamic" have a prior fetch step as source?
        2. Is the sequence the minimum necessary to fulfill the request?
        3. Are all method names valid from the provided list?
        4. Is there a "tool" field on every non-LLM step?
        """
    else:
        return """
        Unknown task type. Default to minimal sequence behavior.
        Return valid JSON only: {"sequence": [{"tool": "...", "method": "...", "args": {}}]}
        """


def build_prompt(tool_name: Union[str, List[str]], methods: List[Dict], user_input: str, task_type: str) -> str:
    if isinstance(tool_name, list):
        tool_section = "Available tools:\n" + "\n".join([f"- {t}" for t in tool_name])
    else:
        tool_section = f"Tool: {tool_name}"

    methods_info = json.dumps(methods, indent=2, ensure_ascii=False)
    template = get_prompt_template(task_type)

    return f"""
    === CONTEXT ===
    {tool_section}
    User request: "{user_input}"

    === AVAILABLE METHODS ===
    {methods_info}

    === GLOBAL RULES ===
    {GLOBAL_RULES}

    === PLANNING INSTRUCTIONS ===
    {template}

    Respond ONLY with a valid JSON object with key "sequence".
    """


def get_decision_prompt(user_input: str, context: str, available_tools: list) -> str:
    if available_tools and isinstance(available_tools[0], str):
        tools_list = [{"name": tool, "description": f"Handles {tool}-related operations"}
                      for tool in available_tools]
    else:
        tools_list = available_tools

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

    AVAILABLE TOOLS:
    {tools_description}

    === TASK TYPES ===
    🟡 complex   → Requires one or more steps using tools, with or without LLM processing.
    🔵 multi_tool → Sequential actions involving DIFFERENT tools or multiple reasoning stages.
    🟣 agent_help → User asking about agent capabilities, how to use it, or needs guidance.
    ⚪ conversation → General chat not requiring tools.

    === DECISION LOGIC ===

    1. Identify the PRIMARY action and resource in the request.
    2. Match each resource to the tool that handles it.
    3. Only include a tool if its functionality is EXPLICITLY required.
    4. Determine task type:
       - complex   → One tool, one or multiple steps
       - multi_tool → Multiple different tools required
       - conversation → No tools needed
       - agent_help → Question about the agent itself

    === RESPONSE FORMAT ===

    Single tool:
    {{"actions": ["tool_name"], "type": "complex"}}

    Multiple tools:
    {{"actions": ["tool_1", "tool_2"], "type": "multi_tool"}}

    No tools:
    {{"actions": [], "type": "conversation"}}

    === AGENT_HELP TRIGGERS ===
    Classify as agent_help when the user asks:
    - About capabilities: "qué puedes hacer", "para qué sirves", "qué funciones tienes"
    - About connecting apps: "cómo conecto Gmail", "cómo autorizar"
    - For help/guidance: "ayuda", "no sé cómo empezar", "no entiendo"
    - Greetings with intent to learn: "hola, qué haces?"

    NOT agent_help (these require tools):
    - "lista mis emails" → {{"actions": ["gmail"], "type": "complex"}}
    - "busca el archivo propuesta" → {{"actions": ["drive"], "type": "complex"}}

    === CRITICAL REMINDERS ===
    - Only include tools DIRECTLY required by the request.
    - Output ONLY valid JSON. No markdown, no backticks, no commentary.
    """


if __name__ == "__main__":
    test_prompt = build_prompt(
        tool_name="drive",
        methods=[
            {"name": "list_files", "signature": "(query: str = None, max_results: int = 10)", "description": "List Google Drive files"},
            {"name": "read_file", "signature": "(file_id: str)", "description": "Read content of a Drive file"},
            {"name": "upload_file", "signature": "(name: str, content: str)", "description": "Upload a file to Drive"},
        ],
        user_input="resume el archivo acta_matricula",
        task_type="complex"
    )
    print(test_prompt)