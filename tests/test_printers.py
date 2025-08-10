import pytest
from fastapi.testclient import TestClient

@pytest.mark.asyncio
async def test_get_all_printers_empty(client: TestClient):
    """Test getting all printers when none are in the database."""
    async for c in client:
        response = c.get("/api/printers")
        assert response.status_code == 200
        assert response.json() == []

@pytest.mark.asyncio
async def test_create_and_get_printer(client: TestClient):
    """Test creating a printer and then getting it."""
    async for c in client:
        # First, create a location for the printer
        location_data = {"name": "Test Lab"}
        response = c.post("/api/locations", json=location_data)
        assert response.status_code == 201

        printer_data = {
            "name": "Test Printer",
            "location": "Test Lab",
            "ip_address": "127.0.0.1",
            "websocket_port": 8765,
            "http_port": 8080,
            "video_port": 8081
        }

        response = c.post("/api/printers", json=printer_data)
        assert response.status_code == 201
        created_printer = response.json()
        assert created_printer["name"] == printer_data["name"]
        assert "id" in created_printer

        response = c.get("/api/printers")
        assert response.status_code == 200
        printers = response.json()
        assert len(printers) == 1
        assert printers[0]["name"] == printer_data["name"]

@pytest.mark.asyncio
async def test_update_printer(client: TestClient):
    """Test updating a printer."""
    async for c in client:
        # First, create a location and a printer
        c.post("/api/locations", json={"name": "Test Lab"})
        printer_data = {
            "name": "Test Printer", "location": "Test Lab", "ip_address": "127.0.0.1",
            "websocket_port": 8765, "http_port": 8080, "video_port": 8081
        }
        response = c.post("/api/printers", json=printer_data)
        printer_id = response.json()["id"]

        # Now, update the printer
        updated_data = {
            "name": "Updated Printer", "location": "Test Lab", "ip_address": "127.0.0.2",
            "websocket_port": 8766, "http_port": 8081, "video_port": 8082
        }
        response = c.put(f"/api/printers/{printer_id}", json=updated_data)
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Printer"
        assert response.json()["ip_address"] == "127.0.0.2"

@pytest.mark.asyncio
async def test_delete_printer(client: TestClient):
    """Test deleting a printer."""
    async for c in client:
        # First, create a location and a printer
        c.post("/api/locations", json={"name": "Test Lab"})
        printer_data = {
            "name": "Test Printer", "location": "Test Lab", "ip_address": "127.0.0.1",
            "websocket_port": 8765, "http_port": 8080, "video_port": 8081
        }
        response = c.post("/api/printers", json=printer_data)
        printer_id = response.json()["id"]

        # Delete the printer
        response = c.delete(f"/api/printers/{printer_id}")
        assert response.status_code == 204

        # Verify it's gone
        response = c.get(f"/api/printers")
        assert len(response.json()) == 0

@pytest.mark.asyncio
async def test_load_filament_to_printer(client: TestClient):
    """Test loading filament to a printer."""
    async for c in client:
        # Create a location, a printer, and a filament
        c.post("/api/locations", json={"name": "Test Lab"})
        printer_data = {
            "name": "Test Printer", "location": "Test Lab", "ip_address": "127.0.0.1",
            "websocket_port": 8765, "http_port": 8080, "video_port": 8081
        }
        printer_id = c.post("/api/printers", json=printer_data).json()["id"]

        filament_data = {
            "name": "Test PLA", "material": "PLA", "color": "Red",
            "spool_weight_grams": 1000, "remaining_weight_grams": 500
        }
        filament_id = c.post("/api/filaments", json=filament_data).json()["id"]

        # Load the filament
        response = c.post(f"/api/printers/{printer_id}/filament", json={"filament_id": filament_id})
        assert response.status_code == 204

        # Verify the printer has the filament loaded
        response = c.get("/api/printers")
        assert response.json()[0]["current_filament_id"] == filament_id
