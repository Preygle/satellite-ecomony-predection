# The final dashboard: any Indian city, end to end

This is the final implementation of the project. You choose a city, and the system fetches its
data, prepares it, trains the image model on that city's own history, tests it on a period it never
saw, forecasts urban and economic-activity growth, reads recent development news, and ranks the
places best suited for a new branch.

```
run_final_dashboard.bat                       # the dashboard, at http://localhost:8501
python -m urbanintel.city.run --city Delhi --estimate-only   # data plan and internet estimate only
python -m urbanintel.city.run --city Delhi                   # the full run, without the dashboard
python -m urbanintel.city.run --city Delhi --from evaluate   # keep data and trained seeds, redo the rest
python -m urbanintel.city.run --city Delhi --from news       # keep everything but the news layer
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
- Located events spread over a radius set by type (airport 10 km, metro 2 km, flyover 1 km). The
  zone index is `tanh(sum / 1.5)`, between -1 and 1, and it is built from located events only: it
  says *where* news matters inside the city. A location that only names the city counts as citywide.
- Citywide and unlocated events form a separate **city news climate**, `tanh(sum / 3)`. It shifts
  every zone of the city equally, so it cannot change where to open a branch, but it does matter
  when comparing cities. In the first Bengaluru run, before this split, about twenty citywide
  events pushed every zone to the top of the scale and the map showed nothing.
- **Evidence check.** A setback status or a negative direction needs a setback word in the headline
  or snippet ("delay", "stall", "scrap", "closure", "flood" and so on). A positive direction needs a
  development word ("open", "approve", "complete", "invest" and so on). Otherwise the label is set to
  neutral, and every override is listed in the results. The rule is the same for good and bad
  news. It was added after the local model labelled "CMRS completes safety inspection of the Pink
  Line" as stalled.
- **One-day changes and other places.** A change that the headline or snippet calls temporary, or
  that lasts "till tomorrow" or "for a day", is not a development, good or bad ("57 Metro stations
  to remain closed till tomorrow"). A story whose places are all a state, district or city outside
  the study area ("Odisha", "Nicobar") is kept in the record but scores nothing; this is checked
  with a settlement search across India. A place that is also a locality inside the city keeps the
  locality (Dwarka in Delhi), and region names that cover the whole study area (NCR, Delhi-NCR)
  count as citywide.

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

**How the dashboard shows it.** The News & developments tab answers "which news affects which part
of the city, and how":

- **A map.** Each development that has a place is a numbered badge (N1, N2, ...), blue if it raises
  the outlook and red if it lowers it, inside a dashed circle showing how far it reaches. The top ten
  expansion sites are numbered circles. Clicking a badge shows the story, its status and evidence,
  and links to the articles.
- **A card per development:** what happened and where, its status and evidence basis, its reach and
  strength, and which top sites it reaches and by how much.
- **Citywide news** as a bar chart, with the city news climate and why it cannot reorder sites.
- **The ranking with and without news:** each top site's score change, its new rank, and the
  development mainly responsible. A site's change is shared among the developments near it in
  proportion to their pull, `impact x exp(-(d/r)^2)`, the same arithmetic as the pipeline.
- **The neutrality checks:** the reader used, the name-swap audit with its re-read baseline, the
  labels set to neutral, and every article read.

The Expansion opportunities tab shows the same "main reason" column, and the Overview names the
most influential mapped development.

**Readers.** Free by default (`--llm auto`):

1. **The Gemini API free tier** (Google AI Studio), if a key is saved as `GEMINI_API_KEY`. It uses
   the best free text model the key can see (`gemini-3.8-flash`, then `gemini-3.6-flash`,
   `gemini-3.5-flash-lite`, ...), with JSON-schema output, at most 12 requests a minute, and moves
   to the next model when one runs out of daily quota. A model that answers 503, or does not answer
   within 60 seconds, is rested for five minutes while the next one is used. On 11 October
   `gemini-3.8-flash` and `gemini-3.6-flash` were overloaded, and `gemini-3.5-flash-lite` read
   every article. Gemini 3 runs at its default temperature with
   low thinking, as Google recommends. Only public headlines and snippets are sent, which matters
   because Google may use free-tier content to improve its products.
2. **A local model through Ollama** (qwen2.5:7b on this machine): free and offline, one request at a
   time, about 4 seconds an article, but weaker. Models under 3 billion parameters are refused because
   they ignore the schema.

The Claude API stays available with `--llm claude`, but it is never chosen automatically. The reader
is picked when the news stage starts, so a key saved part-way through a run is still used, and
`python -m urbanintel.city.run --city <city> --from news` re-reads the news later without
downloading or training again.

Because Gemini 3 runs at its default temperature, the neutrality audit re-reads each tested article
twice: once unchanged and once with names swapped. A swap effect larger than the unchanged
re-read's variation would indicate bias.

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
- **The first Delhi run stopped after 34 of 35 downloads.** One Overpass mirror held the road
  request for seven minutes. The read timeout came from urllib3, which the retry logic did not
  catch, so the road item failed and about 16 MB of road data already received was lost. Errors now
  move to the next mirror, every Overpass answer is cached on disk, and two mirrors that only ever
  returned 500 or hung are dropped. The second run reused the 34 finished downloads and fetched
  only the roads.
- **The neutrality audit compared unlike things.** It set the evidence-checked original against
  unchecked re-reads, so even an identical re-read could count as a change. Both re-reads now pass
  the same check.
- **Gemini's newest models were overloaded.** `gemini-3.8-flash` answered 503 and
  `gemini-3.6-flash` sometimes held a request for minutes. The reader now rests a busy model and
  moves on (§6).
- **Place names that are also buildings.** The geocoder searches inside the study area, so "Odisha"
  in a Delhi story was placed on Odisha Bhawan in Delhi, and "Hyderabad" in a Bengaluru story on a
  place inside Bengaluru carrying that name. The settlement search (§6) now sets such stories
  aside. It also fixed the Hosur battery plant that had been put on Hosur Road in Bengaluru; the
  story now counts citywide. A one-day metro closure counted as a setback until the one-day rule
  was added.

---

## 8. Results: Bengaluru and Delhi

Run on 11 October 2026 with five seeds. The news was first read by the local model (qwen2.5:7b)
and, once a Gemini key was added, read again by `gemini-3.5-flash-lite` from the same articles
(prompt `news-extract-v5`); the table shows the Gemini reading. Every number is in
`data/cities/<city>/results/results.json`.

| | Bengaluru | Delhi |
|---|---|---|
| Study area | 46 x 45 km, 2,139 km², 213,850 cells | 61 x 69 km, 4,371 km², 437,100 cells |
| Landsat dry-season window | October-March; 2000 from two dry seasons | November-April |
| Urban extent 2010 to 2020 (GHS-BUILT-S) | 478 to 622 km² | 1,054 to 1,206 km² |
| **Image model, held-out 2015-2020** | **FoM 0.1765**, AUC 0.931, kappa 0.277 | **FoM 0.2215**, AUC 0.964, kappa 0.348 |
| The five seeds alone | 0.160 to 0.181 | 0.208 to 0.223 |
| Logistic regression, 8 drivers | 0.083 | 0.139 |
| Random placement | 0.016 (the model is 10.9x) | 0.011 (20.0x) |
| Forecast new urban land, 2020 to 2025 | 87.7 km² (622 to 710 km²) | 83.9 km² (1,206 to 1,290 km²) |
| Predicted cells chosen by most seeds | 97% | 92% |
| Night-light growth model, tested on 2020-2024 | Spearman 0.66, top-20% precision 0.37 | Spearman 0.33, top-20% precision 0.32 |
| Past-trend baseline | Spearman 0.49 | Spearman 0.23 |
| Citywide night-light growth | +1.5%/yr 2013-2021, +6.7%/yr 2022-2025 | -0.9%/yr 2013-2021, +7.3%/yr 2022-2025 |
| News: development articles of 140 read | 83 | 77 |
| Developments on the map / citywide / set aside as elsewhere | 6 / 20 / 0 | 8 / 16 / 2 |
| City news climate (-1 to +1) | +0.90 | +0.20 |
| Labels set to neutral by the evidence check | 23 | 30 |
| Name-swap audit: same score (unchanged re-read) | 2 articles: 100% (100%) | 10 articles: 90% (90%) |
| Largest change news makes to a top-ten site | ±0.007; sites 6 and 7 swap | -0.011; four of sites 6 to 9 reorder |
| Top three sites | Gandhinagar; Sir MV Layout; Electronics City Phase 2 | Shipra Sun City (Ghaziabad); IFFCO Chowk (Gurugram); Ralpur Khadar (Noida) |
| Downloaded | 40.9 MB, plus 0.8 MB for a news refresh | 85.8 MB in the stopped first run, 25.5 MB in the second, 0.9 MB for a news refresh |
| Wall-clock time | 39 min | 28 min stopped, then 51 min |

**What this shows.**

- The image model transfers. Trained only on each city's own history, it beats logistic
  regression on the same drivers by 2.1x in Bengaluru and 1.6x in Delhi, and both cities score
  above Varanasi's 0.1507. It is still the same design, with no city-specific tuning.
- The night-light growth model works in Bengaluru and is weak in Delhi. Delhi's Sum of Lights drops
  9% from 2015 to 2016 and stays flat until 2021, while Bengaluru and Chandigarh do not. The timing
  is consistent with Delhi's citywide switch to LED street lights, which the VIIRS day/night band
  sees less well, so a dimming there need not be an economic decline. This is a limit of the proxy,
  stated rather than corrected.
- The news layer depends on its reader. The local 7B model filed almost every development article
  as an "official decision" and found 2 setbacks in Delhi. Gemini spread the same articles over
  reported facts (44 in Bengaluru, 24 in Delhi), official decisions (15, 37) and announcements
  (22, 16), and found 11 setbacks in Delhi, among them delayed drain projects, a construction ban
  and factory closures across the NCR. Delhi's news climate fell from +0.70 to +0.20 as a result.
  The evidence check still set 23 and 30 labels to neutral, mostly positive labels on headlines
  with no development word.
- In Delhi, 9 of 10 audited articles kept their score when party names were swapped, and 9 of 10
  also kept it when re-read unchanged: the swap changed no more than re-reading does. Ten articles
  are too few for a statistical claim.
- News never changes the top five in either city. It swaps sites 6 and 7 in Bengaluru and reorders
  four sites between 6th and 9th in Delhi. This is by design: news is a nudge on top of the
  satellite evidence, not a replacement for it.
- Places are geocoded inside the study area. A place that is also a locality inside the city keeps
  the locality, which is usually right (Dwarka in Delhi) but can be wrong for a same-named
  neighbourhood. Every placement is shown on the News tab map.

**Demo videos** (timelapse x36, wall clock, elapsed time and stage on every frame, chapter list
beside each):

- `data/cities/bengaluru/demo/bengaluru_run_timelapse_20261011-135959.mp4`: 91 s for the 39-minute run
- `data/cities/delhi/demo/delhi_full_story_timelapse.mp4`: 170 s. The stopped first run, a card
  explaining the fix, then the resumed run.

The videos were recorded before the final news fixes, so their news tabs show the first news pass.
The dashboard shows the final one.

