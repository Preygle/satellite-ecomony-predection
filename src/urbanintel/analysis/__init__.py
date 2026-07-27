"""Analytical layers.

Each module takes aligned arrays on the shared `AnalysisFrame` and returns
aligned arrays, so layers compose by plain arithmetic. Nothing here fetches
data — acquisition lives in `urbanintel.data`.
"""

__all__ = ["builtup", "nightlights", "vegetation", "thermal", "ghost", "zonal"]
