import pytest
from fastapi.testclient import TestClient

@pytest.mark.asyncio
async def test_get_all_filaments_empty(client: TestClient):
    """Test getting all filaments when none are in the database."""
    async for c in client:
        response = c.get("/api/filaments")
        assert response.status_code == 200
        assert response.json() == []

@pytest.mark.asyncio
async def test_create_and_get_filament(client: TestClient):
    """Test creating a filament and then getting it."""
    async for c in client:
        filament_data = {
            "name": "Test PLA", "material": "PLA", "color": "Red",
            "spool_weight_grams": 1000, "remaining_weight_grams": 500
        }
        response = c.post("/api/filaments", json=filament_data)
        assert response.status_code == 201
        created_filament = response.json()
        assert created_filament["name"] == filament_data["name"]
        assert "id" in created_filament

        response = c.get("/api/filaments")
        assert response.status_code == 200
        filaments = response.json()
        assert len(filaments) == 1
        assert filaments[0]["name"] == filament_data["name"]

@pytest.mark.asyncio
async def test_update_filament(client: TestClient):
    """Test updating a filament."""
    async for c in client:
        # First, create a filament
        filament_data = {
            "name": "Test PLA", "material": "PLA", "color": "Red",
            "spool_weight_grams": 1000, "remaining_weight_grams": 500
        }
        response = c.post("/api/filaments", json=filament_data)
        filament_id = response.json()["id"]

        # Now, update the filament
        updated_data = {
            "name": "Updated PLA", "material": "PLA+", "color": "Blue",
            "spool_weight_grams": 1000, "remaining_weight_grams": 400
        }
        response = c.put(f"/api/filaments/{filament_id}", json=updated_data)
        assert response.status_code == 200
        assert response.json()["name"] == "Updated PLA"
        assert response.json()["remaining_weight_grams"] == 400

@pytest.mark.asyncio
async def test_delete_filament(client: TestClient):
    """Test deleting a filament."""
    async for c in client:
        # First, create a filament
        filament_data = {
            "name": "Test PLA", "material": "PLA", "color": "Red",
            "spool_weight_grams": 1000, "remaining_weight_grams": 500
        }
        response = c.post("/api/filaments", json=filament_data)
        filament_id = response.json()["id"]

        # Delete the filament
        response = c.delete(f"/api/filaments/{filament_id}")
        assert response.status_code == 204

        # Verify it's gone
        response = c.get("/api/filaments")
        assert len(response.json()) == 0

@pytest.mark.asyncio
async def test_delete_filament_in_use(client: TestClient):
    """Test that a filament in use cannot be deleted."""
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
        c.post(f"/api/printers/{printer_id}/filament", json={"filament_id": filament_id})

        # Try to delete the filament
        response = c.delete(f"/api/filaments/{filament_id}")
        assert response.status_code == 400
