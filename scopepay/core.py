from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse, quote as urlquote
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, StrictInt

ROOT = Path(__file__).resolve().parent.parent
Currency = Literal['USD', 'EUR', 'GBP']  # All have two decimal minor units.
PositiveInt = Annotated[StrictInt, Field(ge=1, le=1000)]
Cents = Annotated[StrictInt, Field(ge=1, le=10_000_000)]


class Problem(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class AnalysisInput(StrictModel):
    source: str = Field(min_length=5, max_length=12000)
    mode: Literal['model', 'manual'] = 'model'


class ExtractedItem(StrictModel):
    title: str = Field(min_length=1, max_length=250)
    quote: str = Field(min_length=3, max_length=1500)


class ExtractedRisk(StrictModel):
    note: str = Field(min_length=1, max_length=400)
    quote: str = Field(min_length=3, max_length=1500)


class Extraction(StrictModel):
    deliverables: list[ExtractedItem] = Field(min_length=1, max_length=20)
    risks: list[ExtractedRisk] = Field(max_length=12)
    questions: list[Annotated[str, Field(min_length=1, max_length=400)]] = Field(max_length=12)


class PriceItem(StrictModel):
    deliverable_id: str = Field(min_length=1, max_length=40)
    quantity: PositiveInt
    unit_cents: Cents


class QuoteInput(StrictModel):
    analysis_id: str = Field(min_length=1, max_length=40)
    currency: Currency
    items: list[PriceItem] = Field(min_length=1, max_length=20)


class Confirmation(StrictModel):
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_currency: Currency
    expected_total_cents: Cents
    acknowledge_scope: Literal[True]


class Empty(StrictModel):
    pass


@dataclass(frozen=True)
class Settings:
    db_path: str = str(ROOT / 'data/scopepay.db')
    payment_mode: str = 'simulation'
    client_id: str = field(default='', repr=False)
    client_secret: str = field(default='', repr=False)
    webhook_id: str = field(default='', repr=False)
    merchant_id: str = field(default='', repr=False)
    app_url: str = 'http://127.0.0.1:8215'
    model_base: str = 'http://127.0.0.1:11435/v1'
    model: str = ''
    model_key: str = field(default='local-not-a-secret', repr=False)
    model_timeout: float = 90
    model_max_tokens: int = 512
    model_source_limit: int = 800
    database_url: str = field(default='', repr=False)

    def __post_init__(self):
        if self.payment_mode not in ('simulation', 'sandbox'):
            raise ValueError('Only simulation or sandbox is supported; production is prohibited.')
        if self.merchant_id and not re.fullmatch(r'[2-9A-HJ-NP-Z]{13}', self.merchant_id):
            raise ValueError('PAYPAL_MERCHANT_ID must be a Sandbox seller account ID.')
        app = urlparse(self.app_url)
        if app.scheme != 'http' or app.hostname not in ('127.0.0.1', 'localhost') or app.path not in ('', '/'):
            raise ValueError('APP_URL must be a loopback HTTP origin for this local MVP.')
        base = urlparse(self.model_base)
        if base.scheme not in ('http', 'https') or base.username or base.password:
            raise ValueError('Invalid model endpoint.')
        if base.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Inference is restricted to the authorized local shared endpoint.')

    @classmethod
    def from_env(cls, env_file=None):
        # A worker can inherit unrelated provider settings. Never silently use
        # them: the project .env wins, and process environment is opt-in.
        selected = Path(env_file) if env_file is not None else ROOT / '.env'
        if env_file is not None and not selected.is_file():
            raise ValueError('Explicit configuration file does not exist.')
        project_env = dotenv_values(selected, interpolate=False)
        use_process = env_file is None and os.getenv('SCOPEPAY_USE_PROCESS_ENV') == '1'
        def setting(key, default=''):
            if key in project_env:
                return project_env[key] or ''
            return os.getenv(key, default) if use_process else default
        path = Path(setting('DATABASE_PATH', 'data/scopepay.db'))
        database_url=setting('SCOPEPAY_DATABASE_URL')
        private_pg_config=setting('SCOPEPAY_PG_CONFIG')
        if private_pg_config and not database_url:
            cfg=json.loads(Path(private_pg_config).read_text(encoding='utf-8-sig'))
            database_url=(f"postgresql://{urlquote(cfg['username'],safe='')}:{urlquote(cfg['password'],safe='')}@"
                          f"{cfg['host']}:{cfg['port']}/{cfg['database']}?sslmode={cfg.get('sslmode','prefer')}")
        return cls(
            database_url=database_url,
            db_path=str(path if path.is_absolute() else ROOT / path),
            payment_mode=setting('PAYMENT_MODE', 'simulation'),
            client_id=setting('PAYPAL_CLIENT_ID'),
            client_secret=setting('PAYPAL_CLIENT_SECRET'),
            webhook_id=setting('PAYPAL_WEBHOOK_ID'),
            merchant_id=setting('PAYPAL_MERCHANT_ID'),
            app_url=setting('APP_URL', 'http://127.0.0.1:8215').rstrip('/'),
            model_base=setting('OPENAI_BASE_URL', 'http://127.0.0.1:11435/v1').rstrip('/'),
            model=setting('OPENAI_MODEL'),
            model_key=setting('OPENAI_API_KEY', 'local-not-a-secret'),
            model_timeout=float(setting('MODEL_TIMEOUT_SECONDS', '90')),
            model_max_tokens=int(setting('MODEL_MAX_TOKENS', '512')),
            model_source_limit=int(setting('MODEL_SOURCE_MAX_CHARS', '800')),
        )


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid4())


def packed(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value) -> str:
    return hashlib.sha256(packed(value).encode('utf-8')).hexdigest()


def money(cents: int) -> str:
    return f'{cents // 100}.{cents % 100:02d}'


# Kept below shared definitions to avoid circular imports. Migration code keeps
# legacy columns byte-for-byte and adds only workflow tables/columns.
from .storage import Store
