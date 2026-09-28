import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    dynamodb_endpoint: str
    table_name: str
    port: int
    ticket_url_template: str


settings = Settings(
    dynamodb_endpoint=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000"),
    table_name=os.getenv("FOREMAN_TABLE", "foreman"),
    port=int(os.getenv("PORT", "8765")),
    ticket_url_template=os.getenv(
        "TICKET_URL_TEMPLATE", "https://linear.app/farsight-ai/issue/{ticket_key}"
    ),
)
