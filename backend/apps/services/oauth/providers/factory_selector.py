from .google_provider import GoogleOAuthProvider
from .microsoft_provider import MicrosoftOAuthProvider
from .hubspot_provider import HubSpotOAuthProvider

def get_oauth_provider(provider_name: str):
    if provider_name == "google":
        return GoogleOAuthProvider()
    elif provider_name == "microsoft":
        return MicrosoftOAuthProvider()
    elif provider_name == "hubspot":
        return HubSpotOAuthProvider()
    else:
        raise ValueError(f"Provider no soportado: {provider_name}")