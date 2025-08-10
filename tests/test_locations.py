import pytest
from fastapi.testclient import TestClient

@pytest.mark.asyncio
async def test_get_all_locations_empty(client: TestClient):
    """Test getting all locations when none are in the database."""
    async for c in client:
        response = c.get("/api/locations")
        assert response.status_code == 200
        assert response.json() == []

@pytest.mark.asyncio
async def test_create_and_get_location(client: TestClient):
    """Test creating a location and then getting it."""
    async for c in client:
        location_data = {"name": "Test Lab"}
        response = c.post("/api/locations", json=location_data)
        assert response.status_code == 201

        response = c.get("/api/locations")
        assert response.status_code == 200
        assert response.json() == ["Test Lab"]

@pytest.mark.asyncio
async def test_delete_location(client: TestClient):
    """Test deleting a location."""
    async for c in client:
        # First, create a location
        location_data = {"name": "Test Lab"}
        c.post("/api/locations", json=location_data)

        # Delete the location
        response = c.delete("/api/locations/Test Lab")
        assert response.status_code == 204

        # Verify it's gone
        response = c.get("/api/locations")
        assert response.status_code == 200
        assert response.json() == []

@pytest.mark.asyncio
async def test_delete_location_in_use(client: TestClient):
    """Test that a location in use cannot be deleted."""
    async for c in client:
        # Create a location and a printer using it
        c.post("/api/locations", json={"name": "Test Lab"})
        printer_data = {
            "name": "Test Printer", "location": "Test Lab", "ip_address": "127.0.0.1",
            "websocket_port": 8765, "http_port": 8080, "video_port": 8081
        }
        c.post("/api/printers", json=printer_data)

        # Try to delete the location
        response = c.delete("/api/locations/Test Lab")
        assert response.status_code == 400
