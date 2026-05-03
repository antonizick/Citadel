import yaml
import os
from pathlib import Path
from app.models import AppSettings

CONFIG_PATH = Path("data/config/settings.yaml")


def get_config() -> AppSettings:
    if not CONFIG_PATH.exists():
        return AppSettings()
    with open(CONFIG_PATH) as f:
        data = yaml.safe_load(f) or {}
    return AppSettings(**data)


def is_dev_mode() -> bool:
    return get_config().system_state.strip().lower() == "dev"


def save_config(settings: AppSettings) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(settings.model_dump(), f, default_flow_style=False)
