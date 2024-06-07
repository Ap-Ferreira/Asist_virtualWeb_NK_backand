import os
import requests
import json
from urllib.parse import unquote

# Webhook URL
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Tool configuration
tool_config = {
    "type": "function",
    "function": {
        "name": "purchase_intent",
        "description": "Detects user interest en un producto o servicio, recopila la información de contacto del usuario y la envía a través de un webhook.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nombre del usuario."
                },
                "email": {
                    "type": "string",
                    "description": "Correo electrónico del usuario."
                },
                "phone_number": {
                    "type": "string",
                    "description": "Número de teléfono del usuario."
                },
                "conversation_summary": {
                    "type": "string",
                    "description": "Resumen breve de la conversación (menos de 30 palabras)."
                }
            },
            "required": ["name", "email", "phone_number", "conversation_summary"]
        }
    }
}

# Callback function
def purchase_intent(arguments):
    """
    Detects user interest in a product or service, collects user contact information, 
    and sends it via a webhook.

    :param arguments: dict, Contains the user's contact information.
                      Expected keys: name, email, phone_number, conversation_summary.
    :return: dict or str, Response from the webhook, error message, or request for correct information.
    """
    # Extract fields
    name = unquote(unquote(arguments.get('name', '')))
    email = arguments.get('email', '')
    phone_number = arguments.get('phone_number', '')
    conversation_summary = arguments.get('conversation_summary', '')

    # Check for missing fields and prompt user
    missing_fields = []
    if not name:
        missing_fields.append("nombre")
    if not email:
        missing_fields.append("correo electrónico")
    if not phone_number:
        missing_fields.append("número de teléfono")
    if not conversation_summary:
        missing_fields.append("resumen de la conversación")

    if missing_fields:
        return f"Por favor proporciona tu {' y '.join(missing_fields)}."

    # Prepare data to send to the webhook
    data = {
        "name": name,
        "email": email,
        "phone_number": phone_number,
        "conversation_summary": conversation_summary
    }

    # Send data to the Webhook URL
    try:
        response = requests.post(WEBHOOK_URL,
                                 headers={"Content-Type": "application/json"},
                                 data=json.dumps(data))
        if response.status_code == 200:
            return "Tu interés ha sido registrado. Nos pondremos en contacto contigo pronto."
        else:
            return f"Error al procesar tu solicitud: {response.text}"
    except requests.exceptions.RequestException as e:
        return f"No se pudo enviar la información al webhook: {e}"
