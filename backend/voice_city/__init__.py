"""Voice City HTTP surface.

``app.py`` mounts the feature with ``from voice_city import voice_city_bp``;
the blueprint itself lives in :mod:`voice_city.api`.
"""
from .api import voice_city_bp

__all__ = ["voice_city_bp"]
