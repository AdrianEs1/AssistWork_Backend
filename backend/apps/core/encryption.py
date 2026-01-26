from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from config import ENCRYPTION_KEY

class TokenEncryption:
    def __init__(self):
        key = ENCRYPTION_KEY
        if not key:
            raise ValueError("ENCRYPTION_KEY no está configurada en .env")

        # Si solo hay una clave:
        self.cipher = Fernet(key.encode())
    
    def encrypt(self, token: str) -> str:
        """Encripta un token"""
        if not token:
            raise ValueError("Token no puede estar vacío")
        return self.cipher.encrypt(token.encode()).decode()
    
    
    def decrypt(self, encrypted_token: str) -> str:
        if not encrypted_token:
            raise ValueError("Token encriptado no puede estar vacío")
        try:
            return self.cipher.decrypt(encrypted_token.encode()).decode()
        except InvalidToken:
            raise ValueError("El token no es válido o la clave de cifrado es incorrecta.")

# Singleton
encryption = TokenEncryption()