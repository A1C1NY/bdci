"""Explicit model routes; secrets remain in local environment or ignored dotenv."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from .storage import read_json

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / ".local" / "models.json"


def load_models(path=None):
    path = Path(path or os.environ.get("RESEARCH_LAB_MODELS_CONFIG") or DEFAULT_CONFIG).resolve()
    if not path.is_file():
        raise ValueError("Missing local model profile; run scripts/setup_member.py or set RESEARCH_LAB_MODELS_CONFIG")
    config = read_json(path)
    if config.get("schema_version") != 1 or not isinstance(config.get("models"), dict) or not config["models"]:
        raise ValueError("Invalid model configuration")
    for alias, model in config["models"].items():
        for field in ("model", "api_key_env", "base_url"):
            if not isinstance(model.get(field), str) or not model[field].strip():
                raise ValueError(f"Missing model field: {alias}/{field}")
        url = urlsplit(model["base_url"])
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Expected credential-free HTTP(S) base URL")
        if model.get("api_format") not in ("chat", "responses"):
            raise ValueError("api_format must be chat or responses")
        if "stream" in model and type(model["stream"]) is not bool:
            raise ValueError("stream must be a boolean")
        aliases = model.get("api_key_env_aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(name, str) or not name.strip() for name in aliases):
            raise ValueError("api_key_env_aliases must contain environment variable names")
        for key in ("token_budget", "input_token_reservation", "max_input_bytes", "max_output_tokens", "timeout_seconds", "max_attempts"):
            if type(model.get(key)) is not int or model[key] <= 0:
                raise ValueError(f"Invalid positive integer {alias}/{key}")
        if model["max_attempts"] > 3 or model["timeout_seconds"] > 1800:
            raise ValueError("At most three attempts and 1800 seconds per attempt")
        if model["input_token_reservation"] < model["max_input_bytes"]:
            raise ValueError("Text input reservation must cover the configured UTF-8 byte allowance")
    if any(alias not in config["models"] for alias in config.get("roles", {}).values()):
        raise ValueError("Unknown model role alias")
    config["ledger_directory"] = str((path.parent / config["ledger_directory"]).resolve())
    config["credentials_file"] = str((path.parent / config["credentials_file"]).resolve())
    return config


def get_key(config, alias):
    model = config["models"][alias]
    names = [model["api_key_env"], *model.get("api_key_env_aliases", [])]
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    path = Path(config["credentials_file"])
    if path.is_file():
        values = {}
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        for name in names:
            if values.get(name):
                return values[name]
    raise ValueError(f"Missing API key environment variable: {names[0]}")
