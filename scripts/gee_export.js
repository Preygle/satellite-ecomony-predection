// ---------------------------------------------------------------- config --
var AOI = ee.Geometry.Rectangle([82.80, 25.15, 83.15, 25.45], 'EPSG:4326', false);
var CRS = 'EPSG:32644';           // UTM 44N — Varanasi
var SCALE = 30;
var FOLDER = 'urbanintel';
var MAX_CLOUD = 35;

var NTL_START = 2013, NTL_END = 2024;
var VEG_YEARS = [2015, 2024];
var LST_YEARS = [2013, 2024];

Map.centerObject(AOI, 11);
Map.addLayer(AOI, {color: '898781'}, 'AOI', false);

// ------------------------------------------------------------ nightlights --
// `average_masked` nulls the background noise floor; the plain `average`
// band would register sensor noise as activity in unlit peri-urban cells.
function nightlights(year) {
  return ee.ImageCollection('NOAA/VIIRS/DNB/ANNUAL_V22')
    .filterDate(year + '-01-01', year + '-12-31')
    .filterBounds(AOI)
    .select('average_masked')
    .mean()
    .unmask(0)
    .rename('nightlights')
    .clip(AOI);
}

// -------------------------------------------------------------- Sentinel-2 --
function s2CloudMask(img) {
  var qa = img.select('QA60');
  var mask = qa.bitwiseAnd(1 << 10).eq(0).and(qa.bitwiseAnd(1 << 11).eq(0));
  return img.updateMask(mask).divide(10000)
            .copyProperties(img, ['system:time_start']);
}

// Oct-Mar window: the Jun-Sep monsoon is heavily clouded, and a full-year
// median would mix post-monsoon flush with dry-season senescence, making
// inter-annual green-cover change unreadable.
function s2Composite(year) {
  return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterDate(year + '-10-01', (year + 1) + '-03-31')
    .filterBounds(AOI)
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', MAX_CLOUD))
    .map(s2CloudMask)
    .median();
}

function ndvi(year) {
  return s2Composite(year).normalizedDifference(['B8', 'B4']).rename('ndvi').clip(AOI);
}
function ndbi(year) {
  return s2Composite(year).normalizedDifference(['B11', 'B8']).rename('ndbi').clip(AOI);
}

// -------------------------------------------------------------------- LST --
// Pre-monsoon (Mar-May): peak surface heat-island season in the
// Indo-Gangetic plain, and the most policy-relevant window.
function lst(year) {
  function prep(img) {
    // QA_PIXEL bits 1-4: dilated cloud, cirrus, cloud, cloud shadow
    // (same mask as src/urbanintel/data/gee.py LANDSAT_QA_MASK_BITS).
    var qa = img.select('QA_PIXEL');
    var clear = qa.bitwiseAnd((1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)).eq(0);
    var st = img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15);
    return st.updateMask(clear).rename('lst').copyProperties(img, ['system:time_start']);
  }
  var l8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
    .filterDate(year + '-03-01', year + '-05-31').filterBounds(AOI).map(prep);
  var l9 = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')
    .filterDate(year + '-03-01', year + '-05-31').filterBounds(AOI).map(prep);
  return l8.merge(l9).median().rename('lst').clip(AOI);
}

// ---------------------------------------------------------- Dynamic World --
function dynamicWorld(year) {
  return ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1')
    .filterDate(year + '-01-01', year + '-12-31')
    .filterBounds(AOI)
    .select(['built', 'trees', 'grass', 'water', 'crops'])
    .mean()
    .clip(AOI);
}

// ------------------------------------------- Open Buildings (2016-2023) ----
// The vertical dimension the other layers miss: a cell whose built-up *area*
// is flat but whose building height is rising is densifying, not expanding.
function buildings(year) {
  return ee.ImageCollection('GOOGLE/Research/open-buildings-temporal/v1')
    .filterDate(year + '-01-01', year + '-12-31')
    .filterBounds(AOI)
    .select(['building_presence', 'building_height', 'building_fractional_count'])
    .mosaic()
    .clip(AOI);
}

// ----------------------------------------------------------------- export --
function exportImage(img, name) {
  Export.image.toDrive({
    image: img,
    description: 'varanasi_' + name,
    folder: FOLDER,
    fileNamePrefix: name,
    region: AOI,
    scale: SCALE,
    crs: CRS,
    maxPixels: 1e10,
    fileFormat: 'GeoTIFF'
  });
}

for (var y = NTL_START; y <= NTL_END; y++) {
  exportImage(nightlights(y), 'ntl_' + y);
}
VEG_YEARS.forEach(function (y) {
  exportImage(ndvi(y), 'ndvi_' + y);
  exportImage(ndbi(y), 'ndbi_' + y);
  exportImage(dynamicWorld(y), 'dw_' + y);
});
LST_YEARS.forEach(function (y) { exportImage(lst(y), 'lst_' + y); });
[2016, 2023].forEach(function (y) { exportImage(buildings(y), 'buildings_' + y); });

// ------------------------------------------------------------- preview -----
Map.addLayer(nightlights(NTL_END), {min: 0, max: 40,
  palette: ['0d366b', '2a78d6', '9ec5f4', 'eda100', 'd03b3b']}, 'Nightlights ' + NTL_END);
Map.addLayer(ndvi(VEG_YEARS[1]), {min: 0, max: 0.7,
  palette: ['f0efec', '9ec5f4', '1baf7a', '008300']}, 'NDVI ' + VEG_YEARS[1], false);
Map.addLayer(lst(LST_YEARS[1]), {min: 25, max: 48,
  palette: ['104281', '3987e5', 'f0efec', 'eda100', 'd03b3b']}, 'LST ' + LST_YEARS[1], false);

print('Export tasks queued — open the Tasks tab and press Run on each.');
print('Nightlight years:', NTL_END - NTL_START + 1);
print('AOI area (km2):', AOI.area().divide(1e6));
