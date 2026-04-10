import os
import asyncio
from typing import Dict, Any, List, Optional
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google.generativeai.types import FunctionDeclaration, Tool
from mcp_config import MCP_CONFIG, ENV


class MCPClientManager:
    """Gestor de sesiones MCP aislado por instancia (una instancia = un usuario)."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stacks: Dict[str, AsyncExitStack] = {}
        self.tool_to_server: Dict[str, Dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    async def connect_server(self, server_name: str):
        """Conecta a un servidor MCP. Si ya está conectado, no hace nada."""
        if server_name in self.sessions:
            return

        server_config = MCP_CONFIG.get(server_name)
        if not server_config:
            raise ValueError(f"No hay configuración para el servidor MCP '{server_name}'")

        config = server_config.get(ENV)
        if not config:
            raise ValueError(f"No hay configuración para '{server_name}' en el entorno '{ENV}'")

        if isinstance(config, dict) and "command" in config:
            server_params = StdioServerParameters(
                command=config["command"],
                args=config.get("args", []),
                env={
                    **os.environ,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                }
            )

            stack = AsyncExitStack()
            self.exit_stacks[server_name] = stack

            try:
                read, write = await stack.enter_async_context(stdio_client(server_params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self.sessions[server_name] = session
                print(f"✅ [{self.user_id[:8]}] Conectado a MCP: {server_name}")
            except Exception as e:
                await stack.aclose()
                del self.exit_stacks[server_name]
                print(f"❌ [{self.user_id[:8]}] Error conectando a {server_name}: {e}")
                raise

        elif isinstance(config, str) and config.startswith("http"):
            raise NotImplementedError("SSE connections not implemented yet.")
        else:
            raise ValueError(f"Configuración inválida para el servidor '{server_name}'")

    async def connect_all(self):
        """Conecta a todos los servidores definidos en MCP_CONFIG."""
        for server_name in MCP_CONFIG.keys():
            await self.connect_server(server_name)

    # ------------------------------------------------------------------
    # Cierre de sesiones
    # ------------------------------------------------------------------

    async def close_server(self, server_name: str):
        """Cierra la sesión de un servidor individual."""
        if server_name in self.exit_stacks:
            await self.exit_stacks[server_name].aclose()
            self.exit_stacks.pop(server_name, None)
            self.sessions.pop(server_name, None)
            print(f"🔌 [{self.user_id[:8]}] Sesión cerrada: {server_name}")

    async def cleanup(self):
        """Cierra todas las sesiones activas de este manager."""
        for server_name in list(self.exit_stacks.keys()):
            await self.close_server(server_name)
        self.tool_to_server.clear()
        print(f"🧹 [{self.user_id[:8]}] Todas las sesiones cerradas.")

    # ------------------------------------------------------------------
    # Herramientas
    # ------------------------------------------------------------------

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        Obtiene todas las herramientas de todos los servidores conectados.
        Retorna una lista de diccionarios con {'server': str, 'tool': tool_object}.
        """
        all_tools_with_context = []

        for server_name, session in self.sessions.items():
            try:
                print(f"🔍 Cargando tools de: {server_name}")
                result = await session.list_tools()

                for tool in result.tools:
                    # Guardamos la herramienta con su contexto de servidor
                    all_tools_with_context.append({
                        "server": server_name,
                        "tool": tool
                    })

                print(f"✅ {server_name}: {len(result.tools)} tools")

            except Exception as e:
                import traceback
                print(f"❌ Error obteniendo tools de {server_name}:")
                traceback.print_exc()

        return all_tools_with_context

    def _clean_schema(self, schema: Any) -> Any:
        if not isinstance(schema, dict):
            return {
                "type": "object",
                "properties": {}
            }

        props = schema.get("properties", {})

        clean_props = {}

        for key, value in props.items():
            if not isinstance(value, dict):
                value = {}

            prop_type = value.get("type")

            # 🔥 Forzar tipo SIEMPRE
            if prop_type not in ["string", "number", "integer", "boolean"]:
                prop_type = "string"

            clean_props[key] = {
                "type": prop_type,
                "description": value.get("description", "")
            }

        return {
            "type": "object",
            "properties": clean_props,
            "required": list(props.keys())  # opcional pero ayuda al LLM
        }

    def to_gemini_tools(self, mcp_tools_with_context: List[Dict[str, Any]]) -> List[Tool]:
        """
        Convierte herramientas MCP a formato Gemini Tool, prefijando nombres para evitar colisiones.
        Ejemplo: 'gmail_send_email', 'teams_list_chats'.
        """
        declarations = []
        self.tool_to_server.clear() # Limpiar mapeo previo

        for item in mcp_tools_with_context:
            server = item["server"]
            tool = item["tool"]
            
            # 🔥 PREFIJO PARA EVITAR COLISIONES (Gemini ValueError)
            prefixed_name = f"{server}_{tool.name}"
            
            try:
                schema = self._clean_schema(tool.inputSchema)

                declarations.append(FunctionDeclaration(
                    name=prefixed_name,
                    description=tool.description or "",
                    parameters=schema
                ))
                
                # Registrar mapeo para call_tool
                self.tool_to_server[prefixed_name] = {
                    "server": server,
                    "original_name": tool.name
                }

            except Exception as e:
                print(f"❌ Tool inválida descartada: {prefixed_name} -> {e}")

        if not declarations:
            return []

        # Retornamos envuelto en Tool
        return [Tool(function_declarations=declarations)]

    # ------------------------------------------------------------------
    # Ejecución de herramientas con reconexión automática
    # ------------------------------------------------------------------

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Llama a una herramienta en su servidor MCP correspondiente usando el nombre prefijado.
        """
        mapping = self.tool_to_server.get(tool_name)
        if not mapping:
            return {
                "success": False,
                "error": f"Herramienta '{tool_name}' no encontrada. Verifica si está conectada."
            }

        server_name = mapping["server"]
        original_name = mapping["original_name"]

        # Reconectar si la sesión no existe
        if server_name not in self.sessions:
            print(f"⚠️  [{self.user_id[:8]}] Sesión '{server_name}' no activa, reconectando...")
            await self.connect_server(server_name)

        try:
            return await self._execute_tool(server_name, original_name, arguments)
        except Exception as e:
            # Intento de reconexión automática ante fallo
            print(f"⚠️  [{self.user_id[:8]}] Fallo en '{server_name}', reconectando: {e}")
            await self.close_server(server_name)
            try:
                await self.connect_server(server_name)
                return await self._execute_tool(server_name, original_name, arguments)
            except Exception as e2:
                return {"success": False, "error": str(e2)}

    async def _execute_tool(self, server_name: str, tool_name: str, arguments: dict) -> dict:
        """Ejecuta la herramienta en la sesión activa del servidor."""
        session = self.sessions[server_name]
        result = await session.call_tool(tool_name, arguments)

        formatted_result = "\n".join(
            item.text for item in result.content if item.type == "text"
        ).strip()

        return {
            "success": not result.isError,
            "result": formatted_result or str(result),
            "isError": result.isError,
        }


# ------------------------------------------------------------------
# Registro global de managers — uno por user_id
# ------------------------------------------------------------------

_managers: Dict[str, MCPClientManager] = {}
_managers_lock = asyncio.Lock()


async def get_manager(user_id: str) -> MCPClientManager:
    """
    Retorna el MCPClientManager asociado al user_id.
    Si no existe, lo crea y conecta todos los servidores.
    Thread-safe con asyncio.Lock.
    """
    async with _managers_lock:
        if user_id not in _managers:
            manager = MCPClientManager(user_id)
            await manager.connect_all()
            _managers[user_id] = manager
        return _managers[user_id]


async def release_manager(user_id: str):
    """
    Cierra y elimina el manager de un usuario (llamar al cerrar sesión).
    """
    async with _managers_lock:
        manager = _managers.pop(user_id, None)
    if manager:
        await manager.cleanup()


async def cleanup_all():
    """Cierra todos los managers activos (usar al apagar el servidor)."""
    async with _managers_lock:
        user_ids = list(_managers.keys())
    for user_id in user_ids:
        await release_manager(user_id)