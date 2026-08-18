"""Data acquisition.

Two paths, deliberately kept separate:

* **Open path** (`ghsl`, `worldpop`, `osm`) — direct HTTP, no credentials.
  The pipeline runs end-to-end on these alone, which is what makes Phase 1
  reproducible on any machine.
* **Earth Engine path** (`gee`) — requires the user to run
  `earthengine authenticate` once. Supplies the sensor-level layers
  (nightlights, NDVI, land surface temperature) that have no open bulk
  download.
"""

__all__ = ["ghsl", "osm", "worldpop", "gee", "download"]
