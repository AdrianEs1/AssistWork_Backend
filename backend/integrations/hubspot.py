import json
from typing import Optional
from apps.services.oauth.hubspot_service_base.hubspot_service_base import HubSpotServiceBase
from apps.services.tool_registry import tool

# --- SERVICE ---
class HubSpotService(HubSpotServiceBase):

    # ── CONTACTOS ──────────────────────────────
    def list_contacts(self, user_id: str, limit: int = 10):
        token = self.get_access_token(user_id)
        return self._request("GET", f"/crm/v3/objects/contacts?limit={limit}&properties=firstname,lastname,email,phone,company", token, user_id=user_id)

    def get_contact_by_email(self, user_id: str, email: str):
        token = self.get_access_token(user_id)
        body = {
            "filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
            "properties": ["firstname", "lastname", "email", "phone", "company"]
        }
        return self._request("POST", "/crm/v3/objects/contacts/search", token, json=body, user_id=user_id)

    def create_contact(self, user_id: str, properties: dict):
        token = self.get_access_token(user_id)
        return self._request("POST", "/crm/v3/objects/contacts", token, json={"properties": properties}, user_id=user_id)

    def update_contact(self, user_id: str, contact_id: str, properties: dict):
        token = self.get_access_token(user_id)
        return self._request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", token, json={"properties": properties}, user_id=user_id)

    def delete_contact(self, user_id: str, contact_id: str):
        token = self.get_access_token(user_id)
        return self._request("DELETE", f"/crm/v3/objects/contacts/{contact_id}", token, user_id=user_id)

    # ── DEALS ──────────────────────────────────
    def list_deals(self, user_id: str, limit: int = 10):
        token = self.get_access_token(user_id)
        return self._request("GET", f"/crm/v3/objects/deals?limit={limit}&properties=dealname,amount,dealstage,closedate", token, user_id=user_id)

    def create_deal(self, user_id: str, properties: dict):
        token = self.get_access_token(user_id)
        return self._request("POST", "/crm/v3/objects/deals", token, json={"properties": properties}, user_id=user_id)

    def update_deal(self, user_id: str, deal_id: str, properties: dict):
        token = self.get_access_token(user_id)
        return self._request("PATCH", f"/crm/v3/objects/deals/{deal_id}", token, json={"properties": properties}, user_id=user_id)

hubspot_instance = HubSpotService()

# ── TOOLS: CONTACTOS ───────────────────────────────────────

@tool(group="hubspot")
async def list_hubspot_contacts(user_id: str, limit: int = 10) -> str:
    """Lista los contactos del CRM de HubSpot."""
    try:
        data = hubspot_instance.list_contacts(user_id, limit)
        contacts = [
            {
                "contact_id": c.get("id"),
                "firstname": c.get("properties", {}).get("firstname"),
                "lastname": c.get("properties", {}).get("lastname"),
                "email": c.get("properties", {}).get("email"),
                "phone": c.get("properties", {}).get("phone"),
                "company": c.get("properties", {}).get("company"),
            }
            for c in data.get("results", [])
        ]
        return json.dumps({"success": True, "count": len(contacts), "contacts": contacts}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="hubspot")
async def get_hubspot_contact(user_id: str, email: str) -> str:
    """Busca un contacto en HubSpot por su email."""
    try:
        data = hubspot_instance.get_contact_by_email(user_id, email)
        results = data.get("results", [])
        if not results:
            return json.dumps({"success": True, "found": False, "message": "No se encontró el contacto"})
        c = results[0]
        return json.dumps({
            "success": True,
            "found": True,
            "contact_id": c.get("id"),
            "properties": c.get("properties", {}),
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="hubspot")
async def create_hubspot_contact(user_id: str, email: str, firstname: str, lastname: str, phone: Optional[str] = None, company: Optional[str] = None) -> str:
    """Crea un nuevo contacto en HubSpot CRM."""
    try:
        properties = {"email": email, "firstname": firstname, "lastname": lastname}
        if phone: properties["phone"] = phone
        if company: properties["company"] = company
        data = hubspot_instance.create_contact(user_id, properties)
        return json.dumps({
            "success": True,
            "contact_id": data.get("id"),
            "status_message": f"✅ Contacto {firstname} {lastname} creado en HubSpot"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="hubspot")
async def update_hubspot_contact(user_id: str, contact_id: str, firstname: Optional[str] = None, lastname: Optional[str] = None, phone: Optional[str] = None, company: Optional[str] = None) -> str:
    """Actualiza propiedades de un contacto existente en HubSpot."""
    try:
        properties = {}
        if firstname: properties["firstname"] = firstname
        if lastname: properties["lastname"] = lastname
        if phone: properties["phone"] = phone
        if company: properties["company"] = company
        hubspot_instance.update_contact(user_id, contact_id, properties)
        return json.dumps({"success": True, "status_message": f"✅ Contacto {contact_id} actualizado"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="hubspot")
async def delete_hubspot_contact(user_id: str, contact_id: str) -> str:
    """Elimina un contacto de HubSpot por su ID."""
    try:
        hubspot_instance.delete_contact(user_id, contact_id)
        return json.dumps({"success": True, "status_message": f"✅ Contacto {contact_id} eliminado"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ── TOOLS: DEALS ───────────────────────────────────────────

@tool(group="hubspot")
async def list_hubspot_deals(user_id: str, limit: int = 10) -> str:
    """Lista los negocios (deals) del pipeline de HubSpot."""
    try:
        data = hubspot_instance.list_deals(user_id, limit)
        deals = [
            {
                "deal_id": d.get("id"),
                "name": d.get("properties", {}).get("dealname"),
                "amount": d.get("properties", {}).get("amount"),
                "stage": d.get("properties", {}).get("dealstage"),
                "close_date": d.get("properties", {}).get("closedate"),
            }
            for d in data.get("results", [])
        ]
        return json.dumps({"success": True, "count": len(deals), "deals": deals}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="hubspot")
async def create_hubspot_deal(user_id: str, dealname: str, amount: Optional[str] = None, dealstage: Optional[str] = None, closedate: Optional[str] = None) -> str:
    """Crea un nuevo negocio (deal) en el pipeline de HubSpot."""
    try:
        properties = {"dealname": dealname}
        if amount: properties["amount"] = amount
        if dealstage: properties["dealstage"] = dealstage
        if closedate: properties["closedate"] = closedate
        data = hubspot_instance.create_deal(user_id, properties)
        return json.dumps({
            "success": True,
            "deal_id": data.get("id"),
            "status_message": f"✅ Deal '{dealname}' creado en HubSpot"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="hubspot")
async def update_hubspot_deal(user_id: str, deal_id: str, dealname: Optional[str] = None, amount: Optional[str] = None, dealstage: Optional[str] = None, closedate: Optional[str] = None) -> str:
    """Actualiza un negocio (deal) existente en HubSpot."""
    try:
        properties = {}
        if dealname: properties["dealname"] = dealname
        if amount: properties["amount"] = amount
        if dealstage: properties["dealstage"] = dealstage
        if closedate: properties["closedate"] = closedate
        hubspot_instance.update_deal(user_id, deal_id, properties)
        return json.dumps({"success": True, "status_message": f"✅ Deal {deal_id} actualizado"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="hubspot")
async def test_hubspot_connection(user_id: str) -> str:
    """Verifica la conexión con HubSpot CRM."""
    result = hubspot_instance.test_connection(user_id)
    return json.dumps(result)