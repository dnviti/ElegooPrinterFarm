# main.py
# To run this backend:
# 1. Install necessary packages: pip install -r requirements.txt
# 2. Run the server: uvicorn main:app --reload

import asyncio
import httpx
import websockets
import uuid
import os
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List
from pydantic import BaseModel
from sqlalchemy import (
    MetaData, Table, Column, String, Integer,
    select, insert, update, delete
)
from sqlalchemy.ext.asyncio import create_async_engine

# --- Database Configuration & SQLAlchemy Setup ---
DATABASE_URL = "sqlite+aiosqlite:///farm.db"
engine = create_async_engine(DATABASE_URL)
metadata = MetaData()

# Define tables using SQLAlchemy Core
printers_table = Table(
    "printers",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("location", String, nullable=False),
    Column("ip_address", String, nullable=False),
    Column("websocket_port", Integer, nullable=False),
    Column("http_port", Integer, nullable=False),
    Column("video_port", Integer, nullable=False),
)

locations_table = Table(
    "locations",
    metadata,
    Column("name", String, primary_key=True),
)

async def create_tables():
    """Creates the database tables and seeds them with initial data if empty."""
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        
        # Seed printers if table is empty
        result = await conn.execute(select(printers_table).limit(1))
        if result.first() is None:
            print("Seeding database with default printer...")
            await conn.execute(insert(printers_table).values(
                id="a1b2c3d4-e5f6-7890-1234-567890abcdef",
                name="Elegoo Centauri Alpha",
                location="Main Workshop",
                ip_address="192.168.1.100",
                websocket_port=8000,
                http_port=80,
                video_port=8080
            ))
        
        # Seed locations if table is empty
        result = await conn.execute(select(locations_table).limit(1))
        if result.first() is None:
            print("Seeding database with default locations...")
            await conn.execute(insert(locations_table).values([
                {"name": "Main Workshop"},
                {"name": "Garage"},
                {"name": "Office"}
            ]))

# --- Pydantic Models for API data validation ---
class PrinterBase(BaseModel):
    name: str
    location: str
    ip_address: str
    websocket_port: int
    http_port: int
    video_port: int

class PrinterCreate(PrinterBase):
    pass

class PrinterUpdate(PrinterBase):
    pass

class Printer(PrinterBase):
    id: str

class LocationCreate(BaseModel):
    name: str

# --- FastAPI Application Setup ---
app = FastAPI(
    title="3D Print Farm Manager API",
    description="Backend server to manage and proxy requests to Elegoo 3D printers.",
    version="1.3.0"
)

@app.on_event("startup")
async def startup_event():
    """On application startup, create the database tables."""
    await create_tables()

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your frontend's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Endpoints ---

# Printer CRUD
@app.get("/api/printers", response_model=List[Printer], tags=["Printers"])
async def get_all_printers():
    async with engine.connect() as conn:
        result = await conn.execute(select(printers_table))
        # Convert SQLAlchemy rows to plain dictionaries so Pydantic can validate them
        return [dict(row) for row in result.mappings().all()]

@app.post("/api/printers", response_model=Printer, status_code=status.HTTP_201_CREATED, tags=["Printers"])
async def create_printer(printer: PrinterCreate):
    async with engine.connect() as conn:
        new_id = str(uuid.uuid4())
        stmt = insert(printers_table).values(id=new_id, **printer.model_dump())
        await conn.execute(stmt)
        await conn.commit()
        return {"id": new_id, **printer.model_dump()}

@app.put("/api/printers/{printer_id}", response_model=Printer, tags=["Printers"])
async def update_printer(printer_id: str, printer_data: PrinterUpdate):
    async with engine.connect() as conn:
        stmt = update(printers_table).where(printers_table.c.id == printer_id).values(**printer_data.model_dump())
        result = await conn.execute(stmt)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Printer not found")
        await conn.commit()
        return {"id": printer_id, **printer_data.model_dump()}

@app.delete("/api/printers/{printer_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Printers"])
async def delete_printer(printer_id: str):
    async with engine.connect() as conn:
        stmt = delete(printers_table).where(printers_table.c.id == printer_id)
        result = await conn.execute(stmt)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Printer not found")
        await conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Location CRUD
@app.get("/api/locations", response_model=List[str], tags=["Locations"])
async def get_all_locations():
    async with engine.connect() as conn:
        result = await conn.execute(select(locations_table.c.name))
        return [row[0] for row in result.fetchall()]

@app.post("/api/locations", status_code=status.HTTP_201_CREATED, tags=["Locations"])
async def create_location(location: LocationCreate):
    async with engine.connect() as conn:
        try:
            stmt = insert(locations_table).values(name=location.name)
            await conn.execute(stmt)
            await conn.commit()
        except Exception: # Catches unique constraint violation
            raise HTTPException(status_code=409, detail="Location already exists")
    return {"message": "Location created successfully"}

@app.delete("/api/locations/{location_name}", status_code=status.HTTP_204_NO_CONTENT, tags=["Locations"])
async def delete_location(location_name: str):
    async with engine.connect() as conn:
        # Check if location is in use
        query = select(printers_table).where(printers_table.c.location == location_name)
        printer_using_location = await conn.execute(query)
        if printer_using_location.first():
            raise HTTPException(status_code=400, detail="Cannot delete location as it is currently in use by a printer.")

        stmt = delete(locations_table).where(locations_table.c.name == location_name)
        result = await conn.execute(stmt)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Location not found")
        await conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- WebSocket and HTTP Proxies ---
async def get_printer_details_from_db(printer_id: str):
    """Helper to fetch printer details for proxies."""
    async with engine.connect() as conn:
        query = select(printers_table).where(printers_table.c.id == printer_id)
        result = await conn.execute(query)
        printer = result.first()
        if not printer:
            return None
        return printer

@app.websocket("/printers/{printer_id}/websocket")
async def websocket_proxy(websocket: WebSocket, printer_id: str):
    printer = await get_printer_details_from_db(printer_id)
    if not printer:
        await websocket.close(code=1008, reason="Printer not found")
        return

    await websocket.accept()
    printer_ws_url = f"ws://{printer.ip_address}:{printer.websocket_port}/websocket"
    try:
        async with websockets.connect(printer_ws_url) as printer_socket:
            print(f"Successfully connected to printer websocket: {printer_ws_url}")
            
            async def forward_to_printer():
                try:
                    while True:
                        message = await websocket.receive_text()
                        await printer_socket.send(message)
                except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed): pass
            
            async def forward_to_client():
                try:
                    while True:
                        message = await printer_socket.recv()
                        await websocket.send_text(message)
                except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed): pass

            await asyncio.gather(forward_to_printer(), forward_to_client())

    except Exception as e:
        print(f"An error occurred in the websocket proxy: {e}")

# --- NEW: Robust Video Proxy using Frame Parsing ---
async def http_proxy_stream(request: Request, target_url: str):
    """
    Proxies a video stream by manually parsing and re-streaming frames.
    This approach is robust against unstable source connections from the printer.
    It reconstructs a clean MJPEG stream for the client.
    """
    boundary = "foo"
    
    async def frame_generator():
        """
        Connects to the printer, parses JPEG frames, and yields them
        formatted for a valid MJPEG stream.
        """
        byte_buffer = b''
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", target_url, timeout=30.0) as response:
                    response.raise_for_status()
                    
                    async for chunk in response.aiter_raw():
                        byte_buffer += chunk
                        
                        start = byte_buffer.find(b'\xff\xd8')
                        end = byte_buffer.find(b'\xff\xd9')
                        
                        if start != -1 and end != -1:
                            jpg_frame = byte_buffer[start:end+2]
                            byte_buffer = byte_buffer[end+2:]
                            
                            yield (
                                f"--{boundary}\r\n"
                                f"Content-Type: image/jpeg\r\n"
                                f"Content-Length: {len(jpg_frame)}\r\n\r\n"
                            ).encode() + jpg_frame + b"\r\n"
        
        except httpx.RequestError as e:
            print(f"Error connecting to printer stream at {target_url}: {e}")
            return
        except Exception as e:
            print(f"An unexpected error occurred while streaming: {e}")
            return

    headers = {
        "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive"
    }
    
    return StreamingResponse(frame_generator(), headers=headers)

# --- Robust Image Proxy ---
async def http_proxy_get_content(target_url: str):
    """
    Proxies a static file (like an image) by downloading it completely
    first, then serving it. This is resilient to unstable source connections.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(target_url, timeout=30.0)
            resp.raise_for_status()
            content_type = resp.headers.get('content-type', 'application/octet-stream')
            return Response(content=resp.content, media_type=content_type)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not retrieve content from printer: {e}")


@app.get("/printers/{printer_id}/video", tags=["Proxy"])
async def video_proxy(request: Request, printer_id: str):
    printer = await get_printer_details_from_db(printer_id)
    if not printer: raise HTTPException(status_code=404, detail="Printer not found")
    target_url = f"http://{printer.ip_address}:{printer.video_port}/video"
    return await http_proxy_stream(request, target_url)

@app.get("/printers/{printer_id}/board-resource/history_image/{task_id}.png", tags=["Proxy"])
async def image_proxy(request: Request, printer_id: str, task_id: str):
    printer = await get_printer_details_from_db(printer_id)
    if not printer: raise HTTPException(status_code=404, detail="Printer not found")
    target_url = f"http://{printer.ip_address}:{printer.http_port}/board-resource/history_image/{task_id}.png"
    return await http_proxy_get_content(target_url)

# --- Frontend Hosting ---
class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as ex:
            if ex.status_code == 404:
                return await super().get_response("index.html", scope)
            raise ex

static_dir_path = "static"
if os.path.isdir(static_dir_path):
    app.mount("/", SPAStaticFiles(directory=static_dir_path, html=True), name="static")
    print("INFO:     Frontend found in 'static' directory. Serving at '/'.")
else:
    print("WARNING:  'static' directory not found. Frontend will not be served.")
    @app.get("/")
    def read_root_fallback():
        return {"message": "3D Print Farm Manager Backend is running. Frontend not found in 'static' directory."}
