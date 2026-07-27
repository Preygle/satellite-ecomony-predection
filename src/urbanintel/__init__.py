"""
urbanintel — Satellite-Based Urban Growth and Economic Activity Intelligence System.

Phase 1 scope: data acquisition, preprocessing, and the five core analytical
layers (built-up growth, economic activity, green cover loss, urban heat,
ghost-growth zones) for a single city, plus an interactive dashboard.
"""

__version__ = "0.1.0"
__phase__ = 1

from .config import Config, load_config  # noqa: F401

__all__ = ["Config", "load_config", "__version__", "__phase__"]
