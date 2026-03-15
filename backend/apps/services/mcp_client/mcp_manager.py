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
        self.tool_to_server: Dict[str, str] = {}

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

    async def get_all_tools(self) -> List[Any]:
        """Obtiene las herramientas de todos los servidores conectados."""
        all_tools = []
        for server_name, session in self.sessions.items():
            result = await session.list_tools()
            for tool in result.tools:
                self.tool_to_server[tool.name] = server_name
                all_tools.append(tool)
        return all_tools

    def _clean_schema(self, schema: Any, is_property: bool = False) -> Any:
        """Limpia atributos no soportados por Gemini recursivamente."""
        if not isinstance(schema, dict):
            return schema

        REMOVE_KEYS = {"title", "default", "$schema", "anyOf", "allOf", "oneOf"}

        cleaned = {}
        for k, v in schema.items():
            if k in REMOVE_KEYS:
                continue
            if k == "properties" and isinstance(v, dict):
                cleaned["properties"] = {
                    prop_name: self._clean_schema(prop_schema, is_property=True)
                    for prop_name, prop_schema in v.items()
                }
            elif isinstance(v, dict):
                cleaned[k] = self._clean_schema(v, is_property=True)
            elif isinstance(v, list):
                cleaned[k] = [
                    self._clean_schema(item, is_property=True) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                cleaned[k] = v

        if is_property and "type" not in cleaned and "properties" not in cleaned:
            cleaned["type"] = "string"

        return cleaned

    def to_gemini_tools(self, mcp_tools: List[Any]) -> List[Tool]:
        """Convierte herramientas MCP a FunctionDeclarations de Gemini."""
        declarations = []
        for tool in mcp_tools:
            schema = self._clean_schema(tool.inputSchema)
            declarations.append(FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=schema
            ))
        return [Tool(function_declarations=declarations)] if declarations else []

    # ------------------------------------------------------------------
    # Ejecución de herramientas con reconexión automática
    # ------------------------------------------------------------------

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Llama a una herramienta en su servidor MCP correspondiente.
        Si la sesión está caída, intenta reconectar una vez automáticamente.
        """
        server_name = self.tool_to_server.get(tool_name)
        if not server_name:
            return {
                "success": False,
                "error": f"Herramienta '{tool_name}' no encontrada en los servidores activos."
            }

        # Reconectar si la sesión no existe
        if server_name not in self.sessions:
            print(f"⚠️  [{self.user_id[:8]}] Sesión '{server_name}' no activa, reconectando...")
            await self.connect_server(server_name)

        try:
            return await self._execute_tool(server_name, tool_name, arguments)
        except Exception as e:
            # Intento de reconexión automática ante fallo
            print(f"⚠️  [{self.user_id[:8]}] Fallo en '{server_name}', reconectando: {e}")
            await self.close_server(server_name)
            try:
                await self.connect_server(server_name)
                return await self._execute_tool(server_name, tool_name, arguments)
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