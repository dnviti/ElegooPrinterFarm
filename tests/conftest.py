import pytest
import asyncio
from typing import AsyncGenerator
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from main import app, metadata, get_db_conn

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(TEST_DATABASE_URL)

async def override_get_db_conn() -> AsyncGenerator:
    async with engine.connect() as connection:
        yield connection

app.dependency_overrides[get_db_conn] = override_get_db_conn

@pytest.fixture
async def client() -> AsyncGenerator:
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    with TestClient(app) as c:
        yield c

    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
