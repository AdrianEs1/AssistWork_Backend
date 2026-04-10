from abc import ABC, abstractmethod

class BaseOAuthProvider(ABC):

    @abstractmethod
    def generate_auth_url(self, user_id: str, scopes: list, state: str):
        pass

    @abstractmethod
    def exchange_code(self, code: str, scopes: list = None):
        pass

    @abstractmethod
    def refresh_token(self, refresh_token: str):
        pass

    @abstractmethod
    def get_user_info(self, access_token: str):
        pass

    def revoke_token(self, token: str) -> bool:
        """Revoca el token (opcional, por defecto no hace nada)"""
        return True