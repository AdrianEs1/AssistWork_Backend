
from fastapi import HTTPException
from .config_integrations import SUPPORTED_INTEGRATIONS


def parse_integration(integration: str):
    try:
        provider, service = integration.split(":")
        return provider, service
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Formato inválido: {integration}"
        )


def get_integration_config(integration: str):
    if integration not in SUPPORTED_INTEGRATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Integración no soportada: {integration}"
        )
    return SUPPORTED_INTEGRATIONS[integration]


def get_provider(integration: str):
    return get_integration_config(integration)["provider"]