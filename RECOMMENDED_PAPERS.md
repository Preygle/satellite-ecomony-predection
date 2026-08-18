# Recommended Reading List — Satellite-Based Urban Growth & Economic Activity Intelligence

Curated 2026-07-26. Citations verified against publisher records unless marked *(unverified)*.

> **Abbreviations.** VIIRS is the Visible Infrared Imaging Radiometer Suite;
> DMSP-OLS is the Defense Meteorological Satellite Program — Operational
> Linescan System; NTL means nighttime light; LULC means land use and land
> cover. Full list in [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).
>
> Paper titles are reproduced exactly as published and are never altered to
> insert an expansion.

---

## Tier 0 — Keep from your existing five

| # | Citation | Why keep |
|---|---|---|
| 1 | Goldblatt, R., Stuhlmacher, M.F., Tellman, B., et al. (2018). *Using Landsat and nighttime lights for supervised pixel-based image classification of urban land cover.* **Remote Sensing of Environment** 205, 253–275. | Method backbone. NTL as weak labels → 30 m built-up classifier, GEE-native, validated on India. |
| 2 | Anucharn, T., Hongpradit, P., Iamchuen, N., Puttinaovarat, S. (2025). *Spatial Analysis of Urban Expansion and Energy Consumption Using Nighttime Light Data.* **ISPRS Int. J. Geo-Inf.** 14(4), 178. DOI: 10.3390/ijgi14040178 | End-to-end GEE workflow template. Modest paper — use as workflow reference, not as evidence. |
| 3 | Tang, Y., Shao, Z., Huang, X., Cai, B. (2021). *Mapping Impervious Surface Areas Using Time-Series Nighttime Light and MODIS Imagery.* **Remote Sensing** 13(10), 1900. DOI: 10.3390/rs13101900 | **Demote to citation.** Superseded operationally by GAIA (#7). |
| — | Chen, X., Wang, Z., Zhang, F., Shen, G., Chen, Q. (2024). *A global annual simulated VIIRS nighttime light dataset from 1992 to 2023.* **Scientific Data** 11, 1380. DOI: 10.1038/s41597-024-04228-6 | Keep **only** if you need pre-2012 baselines. |
| — | Tian, Y., Cheng, K.M., Zhang, Z., et al. (2026). *An Extended VIIRS-like Artificial Nighttime Light Data Reconstruction (1986–2024).* **Scientific Data** 13, 233. DOI: 10.1038/s41597-026-06549-0 | **Drop.** China-only; near-duplicate of Chen 2024. |

---

## Tier 1 — Nighttime lights: use the primary products

| # | Citation | Role |
|---|---|---|
| 4 | Elvidge, C.D., Zhizhin, M., Ghosh, T., Hsu, F.-C., Taneja, J. (2021). *Annual Time Series of Global VIIRS Nighttime Lights Derived from Monthly Averages: 2012 to 2019.* **Remote Sensing** 13(5), 922. DOI: 10.3390/rs13050922 | **VNL V2** — the annual VIIRS series everyone uses. Outlier-removed, background-nulled. In GEE. |
| 5 | Román, M.O., Wang, Z., Sun, Q., et al. (2018). *NASA's Black Marble nighttime lights product suite.* **Remote Sensing of Environment** 210, 113–143. | **VNP46A** — BRDF/atmosphere/moonlight-corrected. Use for *activity change* detection, not raw radiance. GEE: `NASA/VIIRS/002/VNP46A2`. |

Data portals: EOG VNL — https://eogdata.mines.edu/products/vnl/ · Black Marble — https://blackmarble.gsfc.nasa.gov/

---

## Tier 2 — Built-up extent & impervious surface

| # | Citation | Role |
|---|---|---|
| 6 | Brown, C.F., Brumby, S.P., Guzder-Williams, B., et al. (2022). *Dynamic World, Near real-time global 10 m land use land cover mapping.* **Scientific Data** 9, 251. DOI: 10.1038/s41597-022-01307-4 | 10 m NRT LULC, 2015→present. Gives built-up **and** trees **and** grass in one product. Overall accuracy ~73.8%. |
| 7 | Gong, P., Li, X., Wang, J., et al. (2020). *Annual maps of global artificial impervious area (GAIA) between 1985 and 2018.* **Remote Sensing of Environment** 236, 111510. DOI: 10.1016/j.rse.2019.111510 | Annual 30 m global impervious, 1985–2018, >90% OA. Replaces Tang 2021's pipeline. |
| 8 | Marconcini, M., Metz-Marconcini, A., Üreyen, S., et al. (2020). *Outlining where humans live, the World Settlement Footprint 2015.* **Scientific Data** 7, 242. | WSF 2015 (10 m). Companion: WSF **Evolution** (annual 30 m, 1985–2015) — cite Marconcini et al. (2021), *GI_Forum* 9, 33–38. |
| 9 | Pesaresi, M., Politis, P. et al. — **GHSL (Global Human Settlement Layer) GHS-BUILT-S R2023A**. European Commission JRC. https://human-settlement.emergency.copernicus.eu/ghs_buS2023.php | Built-up surface density, 1975–2030, Sentinel-2 + Landsat. Best independent validation baseline. |

---

## Tier 3 — Thermal / urban heat island *(currently a gap in your corpus)*

| # | Citation | Role |
|---|---|---|
| 10 | Ermida, S.L., Soares, P., Mantas, V., Göttsche, F.-M., Trigo, I.F. (2020). *Google Earth Engine Open-Source Code for Land Surface Temperature Estimation from the Landsat Series.* **Remote Sensing** 12(9), 1471. DOI: 10.3390/rs12091471 | **Start here.** Working GEE code, Landsat 4/5/7/8. Repo: https://github.com/sofiaermida/Landsat_SMW_LST |
| 11 | Zhou, D., Xiao, J., Bonafoni, S., et al. (2019). *Satellite Remote Sensing of Surface Urban Heat Islands: Progress, Challenges, and Perspectives.* **Remote Sensing** 11(1), 48. *(volume/article unverified)* | Tells you how to define the urban/rural reference so hotspots aren't artifacts. |

---

## Tier 4 — Ghost / underutilized growth zones *(currently a gap)*

| # | Citation | Role |
|---|---|---|
| 12 | Williams, S., Xu, W., Tan, S.B., Foster, M.J., Chen, C. (2018). *Mapping China's Ghost Cities through the Combination of Nighttime Satellite Data and Daytime Satellite Data.* **Remote Sensing** 10(7), 1037. DOI: 10.3390/rs10071037 | Literally your "built-up high / NTL low" classifier. |
| 13 | Jin, X., Long, Y., Sun, W., Lu, Y., Yang, X., Tang, J. (2017). *"Ghost cities" identification using multi-source remote sensing datasets: A case study in Yangtze River Delta.* **Applied Geography** 80, 112–121. | Multi-source (NTL + built-up + population) identification framework. |
| 14 | *Inferring ghost cities on the globe in newly developed urban areas based on urban vitality with multi-source data.* **Cities** (2025). https://www.sciencedirect.com/science/article/abs/pii/S0197397525000669 | Most recent; global, uses NTL + LST + POI (Point of Interest) + population density as vitality. Closest match to your "ghost growth zone" pillar. |

---

## Tier 5 — Prediction / future expansion *(currently a gap — and a headline feature of your pitch)*

| # | Citation | Role |
|---|---|---|
| 15 | Liang, X., Guan, Q., Clarke, K.C., Liu, S., Wang, B., Yao, Y. (2021). *Understanding the drivers of sustainable land expansion using a patch-generating land use simulation (PLUS) model: A case study in Wuhan, China.* **Computers, Environment and Urban Systems** 85, 101569. DOI: 10.1016/j.compenvurbsys.2020.101569 | **PLUS model** — current standard, beats CA-Markov. Open software: https://github.com/HPSCIL/Patch-generating_Land_Use_Simulation_Model |
| 16 | Chen, G., Li, X., Liu, X., et al. (2020). *Global projections of future urban land expansion under shared socioeconomic pathways.* **Nature Communications** 11, 537. DOI: 10.1038/s41467-020-14386-x | 1 km SSP urban land projections, 2020–2100. Defensible scenario framing for "investment corridors." |
| 17 | *A novel multi-scale deep learning framework for adaptive urban expansion simulation.* **Sustainable Cities and Society** (2025). https://www.sciencedirect.com/science/article/pii/S2210670725004688 | If you want a DL alternative to CA. U-Net++ + attention + autoregressive CA. |

---

## Tier 6 — Economic activity (do this properly, not just nighttime light radiance)

| # | Citation | Role |
|---|---|---|
| 18 | Henderson, J.V., Storeygard, A., Weil, D.N. (2012). *Measuring Economic Growth from Outer Space.* **American Economic Review** 102(2), 994–1028. | Canonical NTL↔GDP elasticity. Sets realistic expectations for what NTL can and cannot infer. |
| 19 | Jean, N., Burke, M., Xie, M., Davis, W.M., Lobell, D.B., Ermon, S. (2016). *Combining satellite imagery and machine learning to predict poverty.* **Science** 353(6301), 790–794. | Transfer learning with NTL as the training signal for daytime imagery. |
| 20 | Yeh, C., Perez, A., Driscoll, A., et al. (2020). *Using publicly available satellite imagery and deep learning to understand economic well-being in Africa.* **Nature Communications** 11, 2583. DOI: 10.1038/s41467-020-16185-w | Modern, better-validated successor to #19. Explains ~70% of variation in held-out countries. |

---

## Tier 7 — Guide-requested sets: VIIRS implementations and U-Net architectures

Requested after the review of Chen et al. (2024). Both sets, the comparison
tables and the derived common trends are in
**[`docs/LITERATURE_NTL_AND_UNET.md`](docs/LITERATURE_NTL_AND_UNET.md)**.

| # | Citation | Set |
|---|---|---|
| 21 | Zheng, Q., Weng, Q., Wang, K. (2019). *Developing a new cross-sensor calibration model for DMSP-OLS and Suomi-NPP VIIRS night-light imageries.* **ISPRS J. Photogramm. Remote Sens.** 153, 36–47. DOI: 10.1016/j.isprsjprs.2019.04.019 | A |
| 22 | Li, X., Zhou, Y., Zhao, M., Zhao, X. (2020). *A harmonized global nighttime light dataset 1992–2018.* **Scientific Data** 7, 168. DOI: 10.1038/s41597-020-0510-y | A |
| 23 | Zhao, M. et al. (2020). *Building a Series of Consistent Night-Time Light Data (1992–2018) in Southeast Asia by Integrating DMSP-OLS and NPP-VIIRS.* **IEEE TGRS** 58(3), 1843–1856. DOI: 10.1109/TGRS.2019.2949797 | A |
| 24 | Chen, Z. et al. (2021). *An extended time series (2000–2018) of global NPP-VIIRS-like nighttime light data from a cross-sensor calibration.* **ESSD** 13, 889–906. DOI: 10.5194/essd-13-889-2021 | A |
| 25 | Nechaev, D. et al. (2021). *Cross-Sensor Nighttime Lights Image Calibration for DMSP/OLS and SNPP/VIIRS with Residual U-Net.* **Remote Sensing** 13(24), 5026. DOI: 10.3390/rs13245026 | **A + B** |
| 26 | Zhang, L. et al. (2024). *A Prolonged Artificial Nighttime-light Dataset of China (1984–2020).* **Scientific Data** 11, 414. DOI: 10.1038/s41597-024-03223-1 | A |
| 27 | Ronneberger, O., Fischer, P., Brox, T. (2015). *U-Net: Convolutional Networks for Biomedical Image Segmentation.* **MICCAI**, LNCS 9351, 234–241. DOI: 10.1007/978-3-319-24574-4_28 | B |
| 28 | Sirko, W. et al. (2021). *Continental-Scale Building Detection from High Resolution Satellite Imagery.* **arXiv:2107.12283** | B |
| 29 | Shojaei, H., Nadi, S., Shafizadeh-Moghadam, H., Tayyebi, A., Van Genderen, J. (2022). *An efficient built-up land expansion model using a modified U-Net.* **Int. J. Digital Earth** 15(1), 148–163. DOI: 10.1080/17538947.2021.2017035 | B |
| 30 | Wang, J., Hadjikakou, M., Hewitt, R.J., Bryan, B.A. (2022). *Simulating large-scale urban land-use patterns and dynamics using the U-Net deep learning architecture.* **Comput. Environ. Urban Syst.** 97, 101855. DOI: 10.1016/j.compenvurbsys.2022.101855 | B |
| 31 | Gui, B., Bhardwaj, A., Sam, L. (2025). *A novel multi-scale deep learning framework for adaptive urban expansion simulation.* **Sustainable Cities and Society** 130, 106594. DOI: 10.1016/j.scs.2025.106594 | B |

Note that #17 in Tier 5 is the same paper as #31; the Tier 5 entry lacked full
bibliographic detail and is superseded by this one.

---

## Notes

- **Green cover loss** is covered operationally by Dynamic World (#6, `trees`/`grass` classes) + NDVI (Normalized Difference Vegetation Index) time series; no dedicated paper needed unless you want a cooling-effect argument, in which case pair #10 and #11 with an NDVI–LST correlation analysis.
- **Caution:** Anucharn 2025's R² ≈ 0.97 for NTL↔electricity is a *province-level aggregate* correlation. Do not cite it as evidence of per-pixel economic inference.
- **Biggest architectural decision:** if your growth window is 2013→present, skip DMSP–VIIRS harmonization entirely (#4/#5 suffice) and drop both Scientific Data harmonization papers.
