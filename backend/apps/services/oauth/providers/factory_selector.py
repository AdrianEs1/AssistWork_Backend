from .google_provider import GoogleOAuthProvider
from .microsoft_provider import MicrosoftOAuthProvider

def get_oauth_provider(provider_name: str):
    if provider_name == "google":
        return GoogleOAuthProvider()
    elif provider_name == "microsoft":
        return MicrosoftOAuthProvider()
    else:
        raise ValueError(f"Provider no soportado: {provider_name}")