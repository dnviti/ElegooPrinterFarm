# main_test.py
import asyncio
import httpx
import websockets
import uuid
import os
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status, Depends
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List
from pydantic import BaseModel
from sqlalchemy import (
    MetaData, Table, Column, String, Integer,
    select, insert, update, delete, create_engine
)
from sqlalchemy.orm import sessionmaker, Session

# --- Database Configuration & SQLAlchemy Setup ---
DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
metadata = MetaData()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    Column("current_filament_id", String, nullable=True),
)

filaments_table = Table(
    "filaments",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("material", String, nullable=False),
    Column("color", String, nullable=False),
    Column("manufacturer", String, nullable=True),
    Column("purchase_price", Integer, nullable=True), # Storing price in cents
    Column("spool_weight_grams", Integer, nullable=False),
    Column("remaining_weight_grams", Integer, nullable=False),
)

locations_table = Table(
    "locations",
    metadata,
    Column("name", String, primary_key=True),
)

def create_tables():
    """Creates the database tables."""
    metadata.create_all(bind=engine)

def drop_tables():
    """Drops the database tables."""
    metadata.drop_all(bind=engine)

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
    current_filament_id: str | None = None

class LoadFilamentRequest(BaseModel):
    filament_id: str | None

class LocationCreate(BaseModel):
    name: str

class FilamentBase(BaseModel):
    name: str
    material: str
    color: str
    manufacturer: str | None = None
    purchase_price: int | None = None
    spool_weight_grams: int
    remaining_weight_grams: int

class FilamentCreate(FilamentBase):
    pass

class FilamentUpdate(FilamentBase):
    pass

class Filament(FilamentBase):
    id: str

# --- Database Dependency ---
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- FastAPI Application Setup ---
app = FastAPI(
    title="3D Print Farm Manager API",
    description="Backend server to manage and proxy requests to Elegoo 3D printers.",
    version="1.3.0"
)

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
def get_all_printers(db: Session = Depends(get_db)):
    result = db.execute(select(printers_table))
    return [dict(row) for row in result.mappings().all()]

@app.post("/api/printers", response_model=Printer, status_code=status.HTTP_201_CREATED, tags=["Printers"])
def create_printer(printer: PrinterCreate, db: Session = Depends(get_db)):
    new_id = str(uuid.uuid4())
    stmt = insert(printers_table).values(id=new_id, **printer.model_dump())
    db.execute(stmt)
    db.commit()
    return {"id": new_id, **printer.model_dump()}

@app.put("/api/printers/{printer_id}", response_model=Printer, tags=["Printers"])
def update_printer(printer_id: str, printer_data: PrinterUpdate, db: Session = Depends(get_db)):
    stmt = update(printers_table).where(printers_table.c.id == printer_id).values(**printer_data.model_dump())
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Printer not found")
    db.commit()
    return {"id": printer_id, **printer_data.model_dump()}

@app.delete("/api/printers/{printer_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Printers"])
def delete_printer(printer_id: str, db: Session = Depends(get_db)):
    stmt = delete(printers_table).where(printers_table.c.id == printer_id)
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Printer not found")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.post("/api/printers/{printer_id}/filament", status_code=status.HTTP_204_NO_CONTENT, tags=["Printers"])
def load_filament_to_printer(printer_id: str, request: LoadFilamentRequest, db: Session = Depends(get_db)):
    # Verify printer exists
    printer_check = db.execute(select(printers_table).where(printers_table.c.id == printer_id)).first()
    if printer_check is None:
        raise HTTPException(status_code=404, detail="Printer not found")

    # Verify filament exists if one is provided
    if request.filament_id:
        filament_check = db.execute(select(filaments_table).where(filaments_table.c.id == request.filament_id)).first()
        if filament_check is None:
            raise HTTPException(status_code=404, detail="Filament not found")

    # Update the printer's current_filament_id
    stmt = update(printers_table).where(printers_table.c.id == printer_id).values(current_filament_id=request.filament_id)
    db.execute(stmt)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/api/printers/{printer_id}/status", tags=["Printers"])
def get_printer_status(printer_id: str, db: Session = Depends(get_db)):
    """Return online/offline status for a printer."""
    printer = db.execute(select(printers_table).where(printers_table.c.id == printer_id)).first()
    if not printer:
        raise HTTPException(status_code=404, detail="Printer not found")
    url = f"http://{printer.ip_address}:{printer.http_port}"
    try:
        with httpx.Client(timeout=2.0) as client:
            client.get(url)
        return {"online": True}
    except Exception:
        return {"online": False}

# Location CRUD
@app.get("/api/locations", response_model=List[str], tags=["Locations"])
def get_all_locations(db: Session = Depends(get_db)):
    result = db.execute(select(locations_table.c.name))
    return [row[0] for row in result.fetchall()]

@app.post("/api/locations", status_code=status.HTTP_201_CREATED, tags=["Locations"])
def create_location(location: LocationCreate, db: Session = Depends(get_db)):
    try:
        stmt = insert(locations_table).values(name=location.name)
        db.execute(stmt)
        db.commit()
    except Exception: # Catches unique constraint violation
        raise HTTPException(status_code=409, detail="Location already exists")
    return {"message": "Location created successfully"}

@app.delete("/api/locations/{location_name}", status_code=status.HTTP_204_NO_CONTENT, tags=["Locations"])
def delete_location(location_name: str, db: Session = Depends(get_db)):
    # Check if location is in use
    query = select(printers_table).where(printers_table.c.location == location_name)
    printer_using_location = db.execute(query).first()
    if printer_using_location:
        raise HTTPException(status_code=400, detail="Cannot delete location as it is currently in use by a printer.")

    stmt = delete(locations_table).where(locations_table.c.name == location_name)
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Location not found")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Filament CRUD
@app.get("/api/filaments", response_model=List[Filament], tags=["Filaments"])
def get_all_filaments(db: Session = Depends(get_db)):
    result = db.execute(select(filaments_table))
    return [dict(row) for row in result.mappings().all()]

@app.post("/api/filaments", response_model=Filament, status_code=status.HTTP_201_CREATED, tags=["Filaments"])
def create_filament(filament: FilamentCreate, db: Session = Depends(get_db)):
    new_id = str(uuid.uuid4())
    stmt = insert(filaments_table).values(id=new_id, **filament.model_dump())
    db.execute(stmt)
    db.commit()
    return {"id": new_id, **filament.model_dump()}

@app.put("/api/filaments/{filament_id}", response_model=Filament, tags=["Filaments"])
def update_filament(filament_id: str, filament_data: FilamentUpdate, db: Session = Depends(get_db)):
    stmt = update(filaments_table).where(filaments_table.c.id == filament_id).values(**filament_data.model_dump())
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Filament not found")
    db.commit()
    return {"id": filament_id, **filament_data.model_dump()}

@app.delete("/api/filaments/{filament_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Filaments"])
def delete_filament(filament_id: str, db: Session = Depends(get_db)):
    # Check if filament is in use
    query = select(printers_table).where(printers_table.c.current_filament_id == filament_id)
    printer_using_filament = db.execute(query).first()
    if printer_using_filament:
        raise HTTPException(status_code=400, detail="Cannot delete filament as it is currently loaded in a printer.")

    stmt = delete(filaments_table).where(filaments_table.c.id == filament_id)
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Filament not found")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
