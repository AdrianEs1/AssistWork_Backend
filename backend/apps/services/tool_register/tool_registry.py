from typing import Callable, Dict, Any
from tools.App_Email.dic_email_tool import GMAIL_TOOL_METHODS
from tools.APP_LocalFiles.dic_local_files_tool import LOCAL_FILES_TOOL_METHODS
#from tools.App_Drive.dic_drive_tool import DRIVE_TOOL_METHODS

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
    
    def register(self, name: str, func: Callable[..., Any], description: str = ""):
        if name in self.tools:
            raise ValueError(f"La tool '{name}' ya está registrada")
        self.tools[name] = {
            "func": func,
            "description": description
        }
    
    def register_tool_group(self, name: str, tool_methods: Dict[str, Dict[str, Any]]):
        """Registra un grupo de herramientas como una sola tool"""
        if name in self.tools:
            raise ValueError(f"La tool '{name}' ya está registrada")
        self.tools[name] = tool_methods
    
    def get(self, name: str):
        return self.tools.get(name)
    
    def list_tools(self):
        return list(self.tools.keys())

TOOL_REGISTRY = ToolRegistry()

# 🔹 Registrar Gmail como un grupo de herramientas
TOOL_REGISTRY.register_tool_group("gmail", GMAIL_TOOL_METHODS)
TOOL_REGISTRY.register_tool_group("LocalFiles", LOCAL_FILES_TOOL_METHODS )
# Registrar Drive como grupo de herramientas
#TOOL_REGISTRY.register_tool_group("drive", DRIVE_TOOL_METHODS) Desactivada por Falta de Scopes necesarios


print("🔧 TOOL_REGISTRY cargado con herramientas:")
for name, tool in TOOL_REGISTRY.tools.items():
    print(f" - {name}: {tool}")
