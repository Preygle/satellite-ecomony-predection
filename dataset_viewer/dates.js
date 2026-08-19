const LAYER_DATES = {
  "truecolour": {
    "composite": "Median of 116 Sentinel-2 scenes on 29 separate days",
    "window": "01 Oct 2024 – 30 Mar 2025",
    "season": "Post-monsoon to dry season (October–March), chosen to avoid monsoon cloud",
    "export": "Exported at 20 m",
    "dataset": "COPERNICUS/S2_SR_HARMONIZED",
    "provider": "ESA / Copernicus",
    "label": "True-colour satellite image"
  },
  "ndvi": {
    "composite": "Median of 116 Sentinel-2 scenes on 29 separate days",
    "window": "01 Oct 2024 – 30 Mar 2025",
    "season": "Post-monsoon to dry season (October–March), chosen to avoid monsoon cloud",
    "export": "Exported at 20 m",
    "dataset": "COPERNICUS/S2_SR_HARMONIZED",
    "provider": "ESA / Copernicus",
    "label": "Vegetation index (NDVI)"
  },
  "ndbi": {
    "composite": "Median of 116 Sentinel-2 scenes on 29 separate days",
    "window": "01 Oct 2024 – 30 Mar 2025",
    "season": "Post-monsoon to dry season (October–March), chosen to avoid monsoon cloud",
    "export": "Exported at 15 m",
    "dataset": "COPERNICUS/S2_SR_HARMONIZED",
    "provider": "ESA / Copernicus",
    "label": "Built-up index (NDBI)"
  },
  "nightlights": {
    "composite": "Annual composite for 2024, cloud- and moonlight-filtered by the provider",
    "window": "01 Jan 2024 – 31 Dec 2024",
    "season": "Full year. Series held covers 2013–2024, twelve annual composites",
    "export": "From ANNUAL_V22, 463 m",
    "dataset": "NOAA/VIIRS/DNB/ANNUAL_V22",
    "provider": "NOAA",
    "label": "Nighttime lights"
  },
  "lst": {
    "composite": "Median of 10 Landsat 8 scenes on 5 separate days",
    "window": "12 Mar 2024 – 15 May 2024",
    "season": "Pre-monsoon (March–May), the hottest, clearest part of the year",
    "export": "30 m",
    "dataset": "LANDSAT/LC08/C02/T1_L2",
    "provider": "USGS",
    "label": "Land surface temperature"
  },
  "dynamicworld": {
    "composite": "Median of 154 classifications on 60 separate days",
    "window": "01 Oct 2024 – 30 Mar 2025",
    "season": "Same window as the Sentinel-2 layers, since it is derived from the same imagery",
    "export": "60 m",
    "dataset": "GOOGLE/DYNAMICWORLD/V1",
    "provider": "Google",
    "label": "Land cover"
  },
  "buildings": {
    "composite": "Annual mosaic for 2023",
    "window": "01 Jan 2023 – 31 Dec 2023",
    "season": "Full year. Product covers 2016–2023",
    "export": "30 m, from 4 m native",
    "dataset": "GOOGLE/Research/open-buildings-temporal/v1",
    "provider": "Google",
    "label": "Building height"
  },
  "builtup": {
    "composite": "GHSL built-up surface for the 2020 epoch",
    "window": "2020 epoch (product covers 1975–2020 observed, five-yearly)",
    "season": "Not seasonal — a modelled annual product",
    "export": "100 m. Downloaded 17 Aug 2026",
    "dataset": "GHS-BUILT-S R2023A",
    "provider": "European Commission Joint Research Centre",
    "label": "Built-up surface"
  },
  "population": {
    "composite": "GHSL population for the 2020 epoch",
    "window": "2020 epoch (product covers 1975–2020 observed, five-yearly)",
    "season": "Not seasonal — a modelled annual product",
    "export": "100 m. Downloaded 17 Aug 2026",
    "dataset": "GHS-POP R2023A",
    "provider": "European Commission Joint Research Centre",
    "label": "Population"
  },
  "poi": {
    "composite": "OpenStreetMap points of interest, as mapped at the time of download",
    "window": "Snapshot taken 17 Aug 2026",
    "season": "Not seasonal — a live database, so this is a point-in-time extract",
    "export": "Vector, gridded to 100 m",
    "dataset": "OpenStreetMap, via the Overpass API",
    "provider": "OpenStreetMap contributors",
    "label": "Points of interest"
  },
  "roads": {
    "composite": "OpenStreetMap roads, as mapped at the time of download",
    "window": "Snapshot taken 17 Aug 2026",
    "season": "Not seasonal — a live database, so this is a point-in-time extract",
    "export": "Vector, gridded to 100 m",
    "dataset": "OpenStreetMap, via the Overpass API",
    "provider": "OpenStreetMap contributors",
    "label": "Road network"
  }
};
