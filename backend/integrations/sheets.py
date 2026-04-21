import json
from typing import Optional, List
from apps.services.oauth.google_service_base.google_service_base import GoogleServiceBase
from apps.services.tool_registry import tool

class SheetsService(GoogleServiceBase):
    def __init__(self):
        super().__init__(service_name="sheets", api_version="v4")

    def _ping_service(self, service):
            # Sheets no tiene getProfile; verificamos con una llamada mínima
            result = service.spreadsheets().get(
                spreadsheetId="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
            ).execute()
            return {"status": "connected", "title": result.get("properties", {}).get("title")}

sheets_instance = SheetsService()

# ─────────────────────────────────────────
# LECTURA
# ─────────────────────────────────────────

@tool(group="sheets")
async def get_spreadsheet_info(user_id: str, spreadsheet_id: str) -> str:
    """Obtiene metadata de un spreadsheet: título, hojas y sus dimensiones."""
    try:
        service = sheets_instance.get_service(user_id)
        result = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = [
            {
                "sheet_id": s["properties"]["sheetId"],
                "title": s["properties"]["title"],
                "rows": s["properties"]["gridProperties"]["rowCount"],
                "columns": s["properties"]["gridProperties"]["columnCount"],
            }
            for s in result.get("sheets", [])
        ]
        return json.dumps({
            "success": True,
            "spreadsheet_id": spreadsheet_id,
            "title": result["properties"]["title"],
            "sheets": sheets,
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="sheets")
async def get_sheet_values(user_id: str, spreadsheet_id: str, range: str) -> str:
    """Lee valores de un rango. Ej: range='Hoja1!A1:D10' o 'A:Z' para toda la hoja."""
    try:
        service = sheets_instance.get_service(user_id)
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range
        ).execute()
        values = result.get("values", [])
        return json.dumps({
            "success": True,
            "range": result.get("range"),
            "total_rows": len(values),
            "values": values,
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="sheets")
async def get_all_sheets(user_id: str, spreadsheet_id: str) -> str:
    """Lista todas las hojas de un spreadsheet con sus IDs y nombres."""
    try:
        service = sheets_instance.get_service(user_id)
        result = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = [
            {
                "sheet_id": s["properties"]["sheetId"],
                "title": s["properties"]["title"],
                "index": s["properties"]["index"],
            }
            for s in result.get("sheets", [])
        ]
        return json.dumps({"success": True, "sheets": sheets}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────────────────────
# ESCRITURA
# ─────────────────────────────────────────

@tool(group="sheets")
async def write_values(user_id: str, spreadsheet_id: str, range: str, values: List[List[str]]) -> str:
    """Escribe valores en un rango. values es una lista de filas, cada fila es una lista de celdas."""
    try:
        service = sheets_instance.get_service(user_id)
        result = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        return json.dumps({
            "success": True,
            "updated_range": result.get("updatedRange"),
            "updated_rows": result.get("updatedRows"),
            "updated_cells": result.get("updatedCells"),
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="sheets")
async def append_rows(user_id: str, spreadsheet_id: str, sheet_name: str, values: List[List[str]]) -> str:
    """Agrega filas al final de la hoja sin sobreescribir datos existentes."""
    try:
        service = sheets_instance.get_service(user_id)
        range = f"{sheet_name}!A1"
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
        updates = result.get("updates", {})
        return json.dumps({
            "success": True,
            "appended_range": updates.get("updatedRange"),
            "appended_rows": updates.get("updatedRows"),
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="sheets")
async def clear_range(user_id: str, spreadsheet_id: str, range: str) -> str:
    """Limpia (borra) todos los valores de un rango específico."""
    try:
        service = sheets_instance.get_service(user_id)
        result = service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=range, body={}
        ).execute()
        return json.dumps({
            "success": True,
            "cleared_range": result.get("clearedRange"),
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="sheets")
async def update_cell(user_id: str, spreadsheet_id: str, cell: str, value: str) -> str:
    """Actualiza una sola celda. Ej: cell='Hoja1!B3', value='nuevo valor'."""
    return await write_values(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        range=cell,
        values=[[value]],
    )


# ─────────────────────────────────────────
# ESTRUCTURA
# ─────────────────────────────────────────

@tool(group="sheets")
async def create_spreadsheet(user_id: str, title: str, sheet_names: Optional[List[str]] = None) -> str:
    """Crea un nuevo spreadsheet con el título dado. sheet_names define las hojas iniciales."""
    try:
        service = sheets_instance.get_service(user_id)
        sheets = [
            {"properties": {"title": name}}
            for name in (sheet_names or ["Hoja1"])
        ]
        result = service.spreadsheets().create(
            body={"properties": {"title": title}, "sheets": sheets}
        ).execute()
        return json.dumps({
            "success": True,
            "spreadsheet_id": result["spreadsheetId"],
            "title": result["properties"]["title"],
            "url": result["spreadsheetUrl"],
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="sheets")
async def add_sheet(user_id: str, spreadsheet_id: str, sheet_name: str) -> str:
    """Agrega una nueva hoja al spreadsheet existente."""
    try:
        service = sheets_instance.get_service(user_id)
        result = service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        ).execute()
        new_sheet = result["replies"][0]["addSheet"]["properties"]
        return json.dumps({
            "success": True,
            "sheet_id": new_sheet["sheetId"],
            "title": new_sheet["title"],
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="sheets")
async def delete_sheet(user_id: str, spreadsheet_id: str, sheet_id: int) -> str:
    """Elimina una hoja por su sheet_id numérico (obtenido con get_all_sheets)."""
    try:
        service = sheets_instance.get_service(user_id)
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
        ).execute()
        return json.dumps({"success": True, "deleted_sheet_id": sheet_id})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="sheets")
async def rename_sheet(user_id: str, spreadsheet_id: str, sheet_id: int, new_name: str) -> str:
    """Renombra una hoja existente por su sheet_id numérico."""
    try:
        service = sheets_instance.get_service(user_id)
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "title": new_name},
                    "fields": "title",
                }
            }]},
        ).execute()
        return json.dumps({"success": True, "new_name": new_name})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool(group="sheets")
async def test_sheets_connection(user_id: str) -> str:
    """Verifica la conexión con la API de Google Sheets."""
    result = sheets_instance.test_connection(user_id)
    return json.dumps(result)