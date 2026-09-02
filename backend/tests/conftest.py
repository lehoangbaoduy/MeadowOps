import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@pytest.fixture(scope="session")
def owner_dsn() -> str:
    password = os.environ["MEADOWOPS_POSTGRES_PASSWORD"]
    return f"host=localhost port=5434 dbname=meadowops user=meadowops password={password}"


@pytest.fixture(scope="session")
def sandbox_dsn() -> str:
    password = os.environ["MEADOWOPS_SANDBOX_ROLE_PASSWORD"]
    return f"host=localhost port=5434 dbname=meadowops user=meadowops_sandbox password={password}"
