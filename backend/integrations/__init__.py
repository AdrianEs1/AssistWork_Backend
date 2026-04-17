# integrations/__init__.py
# Importar los módulos para que el decorador @tool registre las funciones automáticamente

from apps.services.tool_registry import TOOL_REGISTRY
import integrations.gmail
import integrations.teams
import integrations.local_files

__all__ = ["TOOL_REGISTRY"]
