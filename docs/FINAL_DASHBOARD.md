# The final dashboard: any Indian city, end to end

This is the final implementation of the project. You choose a city, and the system fetches its
data, prepares it, trains the image model on that city's own history, tests it on a period it never
saw, forecasts urban and economic-activity growth, reads recent development news, and ranks the
places best suited for a new branch.

```
run_final_dashboard.bat                       # the dashboard, at http://localhost:8501
python -m urbanintel.city.run --city Delhi --estimate-only   # data plan and internet estimate only
python -m urbanintel.city.run --city Delhi                   # the full run, without the dashboard
python scripts/record_demo.py --city Delhi                   # a timestamped timelapse video of a full run
python tests/test_city.py                                    # unit tests for this part
```

Everything for a city is kept in `data/cities/<city>/`: the generated configuration, raw
downloads, rasters, trained models, `status.json` (the live progress the dashboard reads),
`run.log`, `plan.json` (the data plan and estimate) and `results/` (the numbers and map layers).

---

## 1. What happens in a run

The dashboard shows each stage with a progress bar, an x/N counter where the stage has items, the
module that is running, and the megabytes downloaded against the estimate.

| # | Stage | What it does | Module |
|---|---|---|---|
| 1 | Resolving the city boundary | OpenStreetMap boundary through Nominatim; study area = boundary plus a growth belt | `city/catalog.py` |
| 2 | Looking for datasets | Counts clear Landsat dates per year, lists VIIRS years, counts roads and points of interest; writes the plan and the internet estimate | `city/fetch.py` |
| 3 | Downloading datasets | About 35 downloads from Earth Engine and OpenStreetMap, three at a time | `city/fetch.py` |
| 4 | Processing datasets | Every layer onto one 100 m grid in the city's UTM zone | `city/prepare.py` |
| 5 | Training the image model | The unchanged Review 4 trainer, five seeds | `scripts/train_image_v2.py` |
| 6 | Evaluating on the held-out period | Ensemble scored once on 2015-2020, with baselines | `city/model.py` |
| 7 | Forecasting urban growth | 2020 inputs, new urban land by 2025 | `city/model.py` |
| 8 | Analysing economic activity | Night-light trend and a four-year growth model, validated on 2020-2024 | `city/economy.py` |
| 9 | Fetching news information | Balanced topic queries to Google News RSS and GDELT | `city/news.py` |
| 10 | Processing news information | A large language model (LLM) fills a fixed schema; a fixed table scores it | `city/news.py`, `city/llm.py` |
| 11 | Scoring expansion opportunities | Five components, 2,000 random weightings | `city/opportunity.py` |
| 12 | Displaying charts | Map layers reprojected to latitude and longitude | `city/charts.py` |

**Study area.** The OpenStreetMap administrative boundary of the city, plus a buffer of 15% of its
longer side (between 3 and 8 km) because growth happens at the edge, capped at 80 km a side. The
grid uses the city's own UTM zone (Delhi and Bengaluru: EPSG:32643). Search is limited to India,
since the dry-season windows and the WorldPop and census checks are Indian.

---

## 2. Data

| Official identifier | Provider | Used for | How it is fetched |
|---|---|---|---|
| `JRC/GHSL/P2023A/GHS_BUILT_S` (GHS-BUILT-S R2023A) | European Commission JRC | built-up surface 1995-2020, the labels | native 100 m Mollweide grid, then the same reprojection as the bulk tiles |
| `JRC/GHSL/P2023A/GHS_POP` (GHS-POP R2023A) | European Commission JRC | population 1995-2020 | as above |
| `LANDSAT/LT05/C02/T1_L2`, `LANDSAT/LE07/C02/T1_L2`, `LANDSAT/LC08/C02/T1_L2` | USGS | six-band dry-season composites, 1995-2020 | median at 30 m, averaged to 100 m by area on Earth Engine |
| `NOAA/VIIRS/DNB/ANNUAL_V21`, `NOAA/VIIRS/DNB/ANNUAL_V22` | NOAA / Colorado School of Mines | night-time radiance 2013-2025, an economic-activity proxy | on the 100 m grid |
| `GOOGLE/DYNAMICWORLD/V1` | Google and World Resources Institute | water probability 2024, for distance to water | on the 100 m grid |
| `USGS/SRTMGL1_003` | NASA / USGS | terrain slope | slope at 30 m, averaged to 100 m |
| OpenStreetMap (Overpass API; ohsome API for counts) | OpenStreetMap contributors | roads (8 classes) and points of interest | Overpass, gzip, one query at a time |
| Google News RSS, GDELT DOC 2.0 | publishers, via Google News and the GDELT Project | headlines and snippets | 19 Google queries, 2 GDELT queries |

Landsat composites keep the project's rules: Collection 2 Level 2 surface reflectance, QA_PIXEL bits
1-4 masked, Landsat 5 and 7 put on the Landsat 8 scale with Roy et al. (2016), at least four clear
acquisition dates per composite. Two additions for cities other than Varanasi:

- **The dry-season window is chosen per city.** October-March suits north India, but October and
  November are monsoon months in the south. Each city takes the window (October-March,
  November-April or December-May) with the most years above the floor, and uses it for every year so
  its composites stay comparable.
- **A year below the floor combines two dry seasons of that window.** Bengaluru has only three clear
  dates in October 1999-March 2000 in any window, and that year is needed for early stopping. With
  October 1998-March 1999 added it has six. The label says "two dry seasons" wherever it appears.

---

## 3. Urban-growth model

The Review 4 image model, unchanged: 45 channels (30 from imagery, 15 place features), 115,345
parameters, 32 x 32-cell tiles, focal plus Dice loss. The run calls the same script Varanasi used, with
the same settings, and only the city configuration differs.

- **Weights** are fitted on 2010-2015, **early stopping** watches 2000-2005, and **2015-2020** is
  scored once at the end. The three periods do not overlap.
- **Five seeds** are averaged. New urban cells are placed by the project's constrained cellular
  automaton with demand equal to the observed number of conversions, so the Figure of Merit measures
  where growth went, not how much.
- **Baselines** on the same test: random placement, and logistic regression on the eight original
  drivers.
- **Forecast to 2025** uses 2015 and 2020 imagery and 2020 drivers. Demand is the 2010-2020 compound
  growth of urban extent carried forward. For each predicted cell the dashboard shows how many of the
  five seeds placed it, as a measure of uncertainty.

The run checks that the network really has 45 channels. In the first smoke test it had 42: growth
momentum at the 2000 stopping period needs GHSL 1995, which was not being downloaded, and the three
momentum features were dropped for every period. With 1995 added, the Chandigarh smoke test
(one seed) went from a Figure of Merit of 0.109 to 0.149, the same effect momentum had in Varanasi.

---

## 4. Economic activity

**What is measured.** VIIRS (Visible Infrared Imaging Radiometer Suite) annual night-time radiance is
used as a **proxy** for economic activity. It is not GDP and not income. In this project's own check,
night lights track Gross District Domestic Product across 71 Uttar Pradesh districts with Spearman
0.85 (elasticity 0.92), and Economic Census 2013 employment across 10,143 towns and villages with
Spearman 0.41 (`outputs/varanasi_economy_validation.json`).

**What was there before, and what was missing.** The Review 3 system described activity: level,
trend and a ghost-growth typology. It did not forecast growth, which is what a company choosing
where to open a branch needs. The new module adds a forecast and tests it on a period it never saw.

- **Grid.** 500 m zones, close to the VIIRS pixel (about 463 m). 100 m would claim detail the
  sensor does not have.
- **Citywide.** Sum of Lights for every year, with ANNUAL_V21 (2013-2021) and ANNUAL_V22 (2022 on)
  kept apart, since a product change is not growth. Growth is reported within each product.
- **Target.** The change in log radiance over four years, relative to the city's established core:
  the core's median is subtracted each year. This removes citywide brightening and the V2.1 to V2.2
  step, so the model predicts which places will brighten faster than the city.
- **Features.** Current relative level, the trend over the last four years, built-up fraction and
  its five-year growth, population density and its growth, distance to the centre, road density,
  points of interest, the image model's urban-growth probability, and the neighbouring zones' level.
- **Validation.** Trained on 2016-2020, tested once on 2020-2024. Compared with two baselines, no
  change and past trend times four, and with ridge regression. Reported as Spearman rank correlation,
  R², mean absolute error and top-quintile precision (0.20 by chance). A second gradient-boosting
  model without OpenStreetMap features shows how much the present-day road and point-of-interest
  snapshot adds.
- **Forecast.** Refitted on both periods, applied from the latest year (2025 to 2029).

---

## 5. Expansion opportunities

For each 500 m zone that is built up (10% or more in 2020) or forecast to urbanise, five components,
each ranked 0 to 1 among candidates:

| Component | Measure |
|---|---|
| Market now | people within 1.5 km (GHS-POP 2020) |
| Activity now | night-light level over the latest two years |
| Activity growth | the four-year forecast above |
| Urban growth | forecast new urban cells within 1.5 km by 2025 |
| Access | road length per km² within 1 km |

The default weights are equal. Because any choice of weights is a judgement, the score is
recomputed under 2,000 random weightings (Dirichlet(1,...,1)), and each zone reports the share of
weightings in which it stays in the top ten. A share near 1 means the recommendation does not depend
on the weights. Listed sites are at least 1.5 km apart, so the list names distinct places.

---

## 6. Development news

**Retrieval is balanced by design.** 13 neutral topic queries (metro, airport, flyover, IT park and
so on) and 6 setback queries (project delayed, stalled or scrapped, factory closure, flooding, water
shortage, construction ban) to Google News RSS, plus one of each kind to GDELT. Only headlines and
snippets are read; no article text is stored. Articles older than 24 months, and near-duplicates, are
dropped.

**The language model only extracts.** For each article it fills a fixed schema: whether it is a
development, its type (one of 18), direction, status (proposed ... operational, delayed, stalled,
cancelled), basis (reported fact, official decision, announcement, political claim, opinion), scope,
location and a neutral summary. The rules tell it to report only what the text says, to name no
party or politician, to treat promises the same whoever makes them, and to apply the same rules to
good and bad news.

**The score comes from a fixed table, not from the model.**

`impact = effect(type) x status weight x basis weight x 0.5^(age in months / 12) x sign`

- A delay, stall or cancellation is always negative, whatever direction the model gave.
- A political claim or promise has basis weight **0**: it moves nothing.
- Repeated reports of one event are merged, and independent sources raise confidence:
  `min(1, 0.5 + 0.25 x sources)`.
- Located events spread over a radius set by type (airport 10 km, metro 2 km, flyover 1 km).
  Citywide or unlocated events add 0.3 x impact everywhere.
- The zone index is `tanh(sum / 1.5)`, between -1 and 1.

**Neutrality safeguards.**

1. Party names are removed from every output (`[party]`).
2. The scoring table is symmetric: the same event scores +x when it opens and -x when it closes.
3. **A name-swap audit.** Every article that names a party or an office holder is extracted again
   with those names replaced by neutral placeholders. The audit reports the share with the same
   score, and the share that is fully identical.
4. Source concentration (the largest single outlet's share) and the number of articles per query
   are reported.

**The news layer is a qualitative adjustment and is not validated against outcomes.** It changes
the opportunity score by at most ±0.10 on a 0 to 1 scale, and the dashboard always shows the ranking
with and without it.

**Readers.** The Claude API (`claude-opus-5-5` by default, `URBANINTEL_LLM_MODEL` to change it) with
structured outputs, so every answer matches the schema, and server-side fallback if a request is
declined. Or a local model through Ollama (qwen2.5:7b on this machine: free and offline, but weaker).
Models under 3 billion parameters are refused because they ignore the schema.

---

## 7. Checks made while building this

| Check | Result |
|---|---|
| GHSL from the Earth Engine mirror against the JRC bulk tiles, Varanasi 2020 | Native pixels **100% identical**; after reprojection max difference 1e-6 m² (built-up) and 1e-9 persons (population) |
| Landsat averaged to 100 m on Earth Engine against the 30 m export averaged locally, Varanasi 2015 | r ≥ 0.9997 in all six bands, mean difference about 0.0001 reflectance; 1.15 MB instead of 12.7 MB |
| The refactored trainer (shared prediction function, optional forecast) | The untouched original script also gives a different result on a second run (best epoch 130 against the recorded 29): training on this CPU is not bit-reproducible. Seed 0 varies by about ±0.005 in Figure of Merit, which is why five seeds are averaged |
| Channel count on a new city | 42 instead of 45 in the first smoke test (GHSL 1995 missing); fixed, and the run now flags any shortfall |
| Bytes per OpenStreetMap road | 89 bytes per way on the wire with gzip (Chandigarh, 27,667 ways, 2.46 MB) |

**Problems met in practice.**

- Public Overpass servers return 504, 429 and dropped connections under load. Queries now run one
  at a time, wait for a free slot as reported by the server, and give each failing mirror a
  90-second cool-down. Counts for the estimate come from the ohsome API, which stays fast.
- A large Overpass response that fails part-way still costs its bytes. One Chandigarh run used
  11.1 MB on roads where a clean run uses 2.5 MB, so the estimate is a clean-run figure.
- The CARTO base map now needs an API key, so the maps use Esri's light grey canvas.
- `OLLAMA_HOST` on this machine has no `http://` prefix; it is added when missing.
