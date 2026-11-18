"""Application configuration re-export for app package."""

from autopost_nexus.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
