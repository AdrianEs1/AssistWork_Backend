import os
import requests
from datetime import datetime
from config import BREVO_API_KEY, EMAIL_SENDER

def send_email(to_email: str, subject: str, html_content: str):
    """
    Envía un email HTML usando la API v3 de Brevo.
    Mucho más ligero para Cloud Run.
    """
    url = "https://api.brevo.com/v3/smtp/email"
    
    payload = {
        "sender": {"name": "AssistWork", "email": EMAIL_SENDER},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content
    }
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": BREVO_API_KEY
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status() # Lanza error si falla (4xx o 5xx)
        return response.json()
    except Exception as e:
        print(f"❌ Error enviando correo a {to_email}: {e}")
        # Aquí podrías registrar el error en Google Cloud Logging
        return None



def send_reset_email(to_email: str, reset_link: str):
    subject = "Restablece tu contraseña"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8" />
        <title>Restablecer contraseña</title>
    </head>
    <body style="margin:0; padding:0; background:#f4f6f8; font-family:Arial, Helvetica, sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
                <td align="center" style="padding:40px 0;">
                    <table style="max-width:480px; background:#ffffff; border-radius:12px;
                                  box-shadow:0 4px 12px rgba(0,0,0,.08); overflow:hidden;"
                           width="100%">

                        <tr>
                            <td style="padding:24px; text-align:center;
                                       background:linear-gradient(135deg,#06b6d4,#0891b2);
                                       color:#ffffff;">
                                <h1 style="margin:0; font-size:22px;">
                                    Restablecer contraseña
                                </h1>
                            </td>
                        </tr>

                        <tr>
                            <td style="padding:24px; color:#111827;">
                                <p style="font-size:14px;">
                                    Recibimos una solicitud para restablecer tu contraseña.
                                </p>

                                <p style="font-size:14px;">
                                    Haz clic en el botón de abajo para crear una nueva contraseña:
                                </p>

                                <div style="text-align:center; margin:24px 0;">
                                    <a href="{reset_link}"
                                       style="padding:14px 24px; background:#06b6d4;
                                              color:#ffffff; text-decoration:none;
                                              border-radius:8px; font-weight:bold;">
                                        Cambiar contraseña
                                    </a>
                                </div>

                                <p style="font-size:12px; color:#6b7280;">
                                    Este enlace expirará en <strong>30 minutos</strong>.
                                </p>

                                <p style="font-size:12px; color:#6b7280;">
                                    Si no solicitaste este cambio, puedes ignorar este correo.
                                </p>
                            </td>
                        </tr>

                        <tr>
                            <td style="padding:16px; text-align:center;
                                       background:#f9fafb; font-size:11px; color:#9ca3af;">
                                © {datetime.utcnow().year} AssistWork<br/>
                                Seguridad y privacidad primero.
                            </td>
                        </tr>

                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    send_email(to_email, subject, html_content)

def send_delete_account_email(to_email: str, delete_link: str):
    subject = "⚠️ Confirma la eliminación de tu cuenta"

    html_content = f"""
    <div style="font-family: Arial, sans-serif; background:#f8fafc; padding:30px;">
        <div style="max-width:480px; margin:auto; background:#ffffff;
                    padding:24px; border-radius:10px; box-shadow:0 10px 20px rgba(0,0,0,.08);">

            <h2 style="color:#b91c1c; text-align:center;">
                Eliminar cuenta
            </h2>

            <p style="color:#334155; font-size:14px;">
                Recibimos una solicitud para eliminar tu cuenta.
            </p>

            <p style="color:#334155; font-size:14px;">
                <strong>Esta acción es permanente</strong> y eliminará:
            </p>

            <ul style="color:#334155; font-size:14px;">
                <li>Tu cuenta</li>
                <li>Tus conversaciones</li>
                <li>Configuraciones y accesos</li>
            </ul>

            <a href="{delete_link}"
               style="display:block;
                      margin-top:20px;
                      padding:14px;
                      text-align:center;
                      background:#dc2626;
                      color:white;
                      text-decoration:none;
                      border-radius:8px;
                      font-weight:bold;">
                Eliminar cuenta permanentemente
            </a>

            <p style="margin-top:20px; font-size:12px; color:#64748b; text-align:center;">
                Este enlace expira en 30 minutos.
            </p>

            <p style="font-size:12px; color:#64748b; text-align:center;">
                Si no solicitaste esto, ignora este correo.
            </p>

        </div>
    </div>
    """

    send_email(to_email, subject, html_content)

def send_verification_email(to_email: str, code: str):
    subject = "Activa tu cuenta en AssistWork"
    
    html_content = f"""
    <h2>Verificación de cuenta</h2>
    <p>Gracias por registrarte.</p>
    <p>Tu código de activación es:</p>

    <h1 style="letter-spacing: 4px;">{code}</h1>

    <p>Este código expira en 10 minutos.</p>
    """

    send_email(to_email, subject, html_content)

