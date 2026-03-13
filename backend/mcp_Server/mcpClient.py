import os
import asyncio
from typing import Optional, Union
from contextlib import AsyncExitStack

# Librerías base de MCP
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

class MCPClientManager:
    def __init__(self, name: str, connection_info: Union[dict, str]):
        """
        name: Nombre del servidor (ej: "Gmail")
        connection_info: 
            - Si es dict: {"command": "python", "args": ["..."]} (Local)
            - Si es str: "https://gmail-mcp-server.com/sse" (Producción)
        """
        self.name = name
        self.connection_info = connection_info
        self.session: Optional[ClientSession] = None
        self._exit_stack = AsyncExitStack()

    async def connect(self):
        """Establece la conexión detectando el tipo de transporte."""
        try:
            if isinstance(self.connection_info, str) and self.connection_info.startswith("http"):
                # --- MODO PRODUCCIÓN: SSE ---
                print(f"🌐 [MCP {self.name}] Conectando vía Red (SSE)...")
                read, write = await self._exit_stack.enter_async_context(
                    sse_client(url=self.connection_info)
                )
            else:
                # --- MODO LOCAL: STDIO ---
                print(f"💻 [MCP {self.name}] Iniciando proceso local (stdio)...")
                params = StdioServerParameters(
                    command=self.connection_info["command"],
                    args=self.connection_info["args"],
                    env={**os.environ.copy(), "PYTHONUTF8": "1"}
                )
                read, write = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )

            # Inicialización de la sesión (Común para ambos)
            self.session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await self.session.initialize()
            
            tools = await self.session.list_tools()
            print(f"✅ [MCP {self.name}] {len(tools.tools)} herramientas listas.")
            return tools.tools

        except Exception as e:
            await self.disconnect()
            raise Exception(f"Fallo de conexión en {self.name}: {e}")

    async def call_action(self, tool_name: str, arguments: dict):
        """Ejecuta la herramienta y devuelve el CallToolResult."""
        if not self.session:
            raise Exception(f"Sesión no activa para {self.name}")
        
        # El protocolo maneja la serialización por ti
        return await self.session.call_tool(tool_name, arguments)

    async def disconnect(self):
        """Cierre limpio de recursos y procesos."""
        await self._exit_stack.aclose()
        self.session = None
        print(f"🔌 [MCP {self.name}] Desconectado.")