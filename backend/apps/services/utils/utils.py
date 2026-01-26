import inspect

def get_function_signature(func):
    """Obtiene la firma completa de una función"""
    try:
        sig = inspect.signature(func)
        params = []
        for name, param in sig.parameters.items():
            if name == 'self':
                continue
            
            param_info = f"{name}"
            if param.annotation != inspect.Parameter.empty:
                param_info += f": {param.annotation.__name__ if hasattr(param.annotation, '__name__') else param.annotation}"
            if param.default != inspect.Parameter.empty:
                param_info += f" = {param.default}"
            
            params.append(param_info)
        
        return f"{func.__name__}({', '.join(params)})"
    except:
        return f"{func.__name__}(...)"

def filter_valid_args(func, args: dict) -> dict:
    """Filtra argumentos válidos según la firma de la función"""
    try:
        sig = inspect.signature(func)
        valid_params = set(sig.parameters.keys()) - {'self'}
        return {k: v for k, v in args.items() if k in valid_params and v is not None}
    except:
        return args
    
async def should_continue_after_error(user_input: str, failed_method: str, error: str, current_step: int, total_steps: int) -> bool:
    """Determina si continuar después de un error"""
    
    # Errores críticos que siempre detienen la ejecución
    critical_errors = ["authentication", "permission", "not_found", "invalid_credentials"]
    if any(critical in error.lower() for critical in critical_errors):
        return False
    
    # Si es el último paso, no tiene sentido continuar
    if current_step == total_steps:
        return False
    
    # Para errores menores, intentar continuar
    minor_errors = ["timeout", "rate_limit", "temporary"]
    if any(minor in error.lower() for minor in minor_errors):
        print(f"⚠️ Error menor detectado, intentando continuar...")
        return True
    
    return False