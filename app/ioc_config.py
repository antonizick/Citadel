"""IOC source configuration — stored separately from main app settings."""
import yaml
from pathlib import Path
from pydantic import BaseModel

IOC_CONFIG_PATH = Path("data/config/ioc_sources.yaml")


class IocSourceConfig(BaseModel):
    enabled: bool = True
    api_key: str = ""


class IocSourcesSettings(BaseModel):
    feodo_tracker: IocSourceConfig = IocSourceConfig()
    urlhaus: IocSourceConfig = IocSourceConfig()
    malwarebazaar: IocSourceConfig = IocSourceConfig()
    openphish: IocSourceConfig = IocSourceConfig()
    threatfox: IocSourceConfig = IocSourceConfig(enabled=False)
    otx: IocSourceConfig = IocSourceConfig(enabled=False)


def get_ioc_config() -> IocSourcesSettings:
    if not IOC_CONFIG_PATH.exists():
        return IocSourcesSettings()
    with open(IOC_CONFIG_PATH) as f:
        data = yaml.safe_load(f) or {}
    return IocSourcesSettings(**data)


def save_ioc_config(cfg: IocSourcesSettings) -> None:
    IOC_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(IOC_CONFIG_PATH, "w") as f:
        yaml.dump(cfg.model_dump(), f, default_flow_style=False)
