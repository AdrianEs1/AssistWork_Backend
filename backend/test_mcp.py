import asyncio
import os
#from apps.mcp.client_manager import MCPClientManager # Ajusta según tu estructura
from mcp_Server.mcpClient import MCPClientManager

async def test_handshake():
    # 1. Configuración local (Modo Desarrollo)
    # Asegúrate de que la ruta apunte a tu archivo migrado de Gmail
    connection_info = {
        "command": "python",
        "args": ["-m", "mcp_Server.GMAIL_ServerMCP"] 
    }
    
    client = MCPClientManager("Gmail-Test", connection_info)
    
    print("🛠️  Iniciando prueba de conexión MCP...")
    
    try:
        # 2. Intentar conexión y handshake
        # Esto valida: 1. El proceso arranca, 2. STDIO funciona, 3. initialize() exitoso
        tools = await client.connect()
        
        print(f"\n✅ ¡Conexión establecida con éxito!")
        print(f"📦 Servidor: {client.name}")
        print(f"🔧 Herramientas encontradas ({len(tools)}):")
        
        for tool in tools:
            print(f"   - {tool.name}: {tool.description[:60]}...")
            
        # 3. Prueba de fuego: Llamar a una herramienta simple
        # Probamos 'test_connection' que ya definimos en el servidor
        print("\n🧪 Probando ejecución de herramienta 'test_connection'...")
        
        # Ojo: Pasa un user_id que exista en tu lógica para que no falle el service base
        result = await client.call_action("test_connection", {"user_id": "test_user_adrian"})
        
        print(f"📊 Resultado del servidor: {result.content[0].text}")
        
    except Exception as e:
        print(f"\n❌ Falló la prueba de conexión:")
        print(f"Error: {str(e)}")
        
    finally:
        # 4. Limpieza: Validamos que AsyncExitStack cierre el proceso
        await client.disconnect()
        print("\n🔌 Proceso cerrado limpiamente.")

if __name__ == "__main__":
    asyncio.run(test_handshake())