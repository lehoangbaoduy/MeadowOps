from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """No module-level singleton — `create_app(settings=...)` constructs one
    per call, so tests can monkeypatch/override cleanly instead of fighting
    an import-time-cached global."""

    model_config = SettingsConfigDict(env_prefix="MEADOWOPS_", extra="ignore")

    builder_token: str = Field(min_length=1)
    # DD-11: Settings stays authoritative only for values the FastAPI app
    # process itself consumes. Unit 8 is the first unit where the app opens
    # its own DB connection (admin CRUD), so database_url joins builder_token
    # here — everything upstream of the app (migrations, seeders, test
    # fixtures) keeps reading MEADOWOPS_DATABASE_URL via plain os.environ.
    database_url: str = Field(min_length=1)
