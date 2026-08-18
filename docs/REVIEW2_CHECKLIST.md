# Review 2 — Rubric Mapping and Panel Preparation

**BCSE497J Project I · Review 2 (Panel) · 19 August 2026 · 20 marks**

---

## 1. Rubric mapping

Where each criterion is evidenced, and an honest assessment of strength.

### 1 · Domain understanding and problem definition — 3 marks

| Evidence | Location |
|---|---|
| Domain context, urbanisation in Indian cities, why Varanasi | Report §1.1 |
| Four-part problem statement with distinct deficiencies | Report §1.2 |
| Assumptions and constraints stated | Report §1.4, §3.6 |
| Significance argued fiscally, not only technically | Report §1.2(b), §2.3 |

**Strength: strong.** The problem is specific and the significance argument
(leapfrog development costs more per household to service) is concrete rather
than generic.

**Exposure:** the panel may ask why Varanasi specifically. Answer below (Q1).

---

### 2 · Literature/patent review and analysis — 3 marks

| Evidence | Location |
|---|---|
| Six literature strands, 18 sources | Report §2.1–2.6 |
| Comparison table of 8 approach families with limitations | Report Table 2.1 |
| Six explicitly identified gaps, each mapped to a design response | Report Table 2.2 |
| Full source list with verified DOIs | Report References; `RECOMMENDED_PAPERS.md` |

**Strength: strong.** Every citation has been verified against publisher
records. The gap analysis is mapped to specific design decisions rather than
being decorative.

**Gap: no patent search.** The rubric says "literature **or** patent review",
so literature alone is compliant — but if asked, say plainly that a patent
search was not conducted and that it is a reasonable addition.

---

### 3 · Objectives, scope and expected outcomes — 2 marks

| Evidence | Location |
|---|---|
| Seven objectives, each with a measurable outcome | Report §1.3 |
| Explicit in-scope and out-of-scope lists | Report §1.4 |
| Deliberate boundary — "screening tool, not census" | Report §1.4 |
| Expected outcomes enumerated | Report §1.5 |

**Strength: strong.** The out-of-scope list is unusually explicit, which reads
as considered rather than evasive.

---

### 4 · Proposed methodology — 3 marks

| Evidence | Location |
|---|---|
| Five-stage method with a stated organising principle | Report §3.1 |
| Six algorithms specified in detail | Report §3.5 |
| Every threshold justified in a table | Report Table 3.3 |
| Three explicit methodological contributions | Report §3.5.3(i)–(iii) |

**Strength: strongest section.** The learned-expectation approach is a genuine
methodological choice with a defensible rationale, not an application of a
standard recipe.

---

### 5 · System architecture and module design — 3 marks

| Evidence | Location |
|---|---|
| Five-layer architecture diagram | Report Figure 3.1 |
| Dual-path acquisition design | Report Figure 3.2 |
| Module responsibility table with interfaces | Report Table 3.1 |
| Ghost-growth workflow diagram | Report Figure 3.3 |
| Working code | Repository |

**Strength: strong** — architecture is implemented, not hypothetical.

**Action:** export the Mermaid diagrams as PNG/SVG for the Word report and the
slides; they will not render in Word.

---

### 6 · Feasibility, risks, ethics and work planning — 3 marks

| Evidence | Location |
|---|---|
| Feasibility demonstrated by working implementation | Report §4.1 |
| Eight-item risk register with status | Report Table 4.1 |
| Data licensing, privacy, misuse analysis | Report §4.3 |
| **AI-use disclosure** | Report Appendix A |
| Timeline against actual review dates | Report Figure 4.1, Table 4.2 |

**Strength: strong, and commonly under-attempted.** Most teams treat this
section as boilerplate; the misuse analysis and the risk register with
*mitigation status* are differentiators.

**Do not remove the AI disclosure.** Undisclosed AI use is explicitly
prohibited by §2 of the guidelines.

---

### 7 · Preliminary report quality and presentation — 3 marks

| Evidence | Location |
|---|---|
| Chapters 1–3 complete, plus Chapter 4 | `docs/REVIEW2_REPORT.md` |
| Preliminary pages structured per guidelines §5 | Report header |
| Lists of figures, tables, abbreviations | Report front matter |
| Consistent citation style | Report References |

**Outstanding before submission** — see §2.

---

## 2. Before submission — action list

| # | Action | Why |
|---|---|---|
| 1 | Fill student name(s), registration number(s), guide name | Placeholders present |
| 2 | Add bonafide certificate, declaration, acknowledgement | Required preliminary pages |
| 3 | **Complete the individual contribution statement** | Guidelines require each member's contribution to be demonstrable |
| 4 | **Review and amend Appendix A to match actual practice** | It must describe what genuinely happened, not what I assumed |
| 5 | Export Mermaid diagrams as images | They will not render in Word/PDF |
| 6 | Convert to institutional report template | Formatting compliance |
| 7 | Run similarity check | Guidelines require compliance with institutional similarity limits |
| 8 | Confirm referencing style with guide | Currently IEEE-style; institution may prescribe otherwise |
| 9 | Add Review 1 feedback and action taken | Guidelines §2: review comments must be recorded and the action presented |

Item 9 matters — the guidelines state that *"all review comments and
suggestions shall be recorded, and the action taken shall be presented during
the subsequent review."* I have no record of your Review 1 feedback. If the
panel asks what changed since Review 1 and there is no answer, that is an
avoidable loss.

---

## 3. Anticipated panel questions

**Q1 — Why Varanasi?**

A mid-sized Indian city undergoing rapid infrastructure investment with weak
spatial monitoring — which is the condition the system is designed for, and
which is far more common nationally than the metro case. It also provides a
useful methodological stress test: the Ganga bisects the area of interest,
which forces correct handling of water in the heat-island baseline, and the
surrounding intensive agriculture forces correct attribution of NDVI (Normalized Difference Vegetation Index) change.

**Q2 — Nighttime lights are only ~460 m. How can you claim anything about
specific developments?**

We do not. The unit of a reliable finding is a neighbourhood, not a building,
and that constraint is stated in the report, the code and the dashboard. The
smallest reported zone is 0.26 km². The system is positioned as a screening
tool that directs inspection.

**Q3 — What stops you flagging an industrial estate or a park as a ghost
zone?**

Three things. Activity is normalised per unit of built-up area, so a large
low-activity site is not penalised for its size. Expected activity is learned
from the city's own built-up/activity relationship, so the comparison is
against similar land. And the flag requires the development to be recent —
long-standing low-activity land is classified `declining`, a different
category.

**Q4 — Your ghost figure is 0.35 km². How confident are you?**

More confident than we were, and the reason is worth stating because it is the
strongest evidence the method works as designed.

An earlier run reported **7.24 km²** and labelled it an upper bound in the
system's own output, on the grounds that without a nighttime-light time series
a neighbourhood filling up cannot be separated from one that never will. The
full VIIRS (Visible Infrared Imaging Radiometer Suite) series 2013–2024 has since been integrated, and the 7.24 km² split
almost exactly: **0.35 km² genuinely dim and not rising, 6.88 km² emerging**.
The stated caveat was correct, and the correction went in the predicted
direction — by a factor of twenty.

Two honest qualifications. First, **there is still no ground truth**;
validation against high-resolution imagery or a site visit is Phase 3, and at
0.35 km² the zones are small enough — some are four 50 m cells — that a single
mapping error could produce one. Zones 14 and 15, at scores 0.56 and 0.50, are
the boundary of the method's discrimination and should be presented as such.
Second, all 15 zones are peripheral, and the nighttime-light literature finds
that residual error in NTL products concentrates at exactly the urban fringe
(`LITERATURE_NTL_AND_UNET.md` §3.4). Using observed VIIRS rather than a
simulated long series avoids the worst of that, but not all of it.

**Q4b — If the number moved by 20×, why should we trust the new one?**

Because the *structure* did not change — only the input completeness did. The
classifier, thresholds and expected-activity curve are unchanged; the activity
index went from two signals to three, and the third carries the largest weight
(0.45). A screening tool missing its largest single weight does not produce a
conservative estimate, it produces one that is wrong by an order of magnitude,
and the earlier report said so in advance rather than in hindsight.

**Q5 — What is novel here?**

Three things. The expectation is learned from each city's own data rather than
set as a threshold, which makes the method transferable. The nighttime-light
trend distinguishes "not yet occupied" from "never occupied", which
single-epoch studies cannot. And urban form and utilisation are computed on a
shared frame, so the relationship between leapfrog development and
under-occupancy can be tested rather than assumed — in Varanasi, 48.8%
leapfrog and nine peripheral ghost zones are mutually consistent.

**Q6 — How do you know the implementation is correct?**

Twenty automated tests over the analytical logic, including synthetic cases
with known answers. Beyond that, four substantive defects were found and fixed
during development — a frame-alignment error, a resolution-dependent
threshold, an unreachable threshold, and an aggregation method that erased
minority findings. Three were caught by disbelieving implausible output rather
than by tests, which is itself worth reporting: the pipeline "ran" throughout.

**Q7 — Why not just use Google Earth Engine for everything, as most papers do?**

Because it makes the whole project contingent on account approval. The dual
path means the credential-free sources produce complete expansion, activity
and ghost-growth results, and Earth Engine strengthens rather than enables.
That was the correct call in practice — Earth Engine authentication is still
outstanding and the system has produced full results regardless.

**Q8 — Could this be misused against informal settlements?**

Yes, and it is addressed in §4.3. An "underutilised land" determination could
support displacement or punitive action against populations least able to
contest it. The mitigations are: positioning as screening requiring ground
verification, surfacing confidence limits in the output itself, explicitly
documenting the bias against sparsely-mapped peripheral areas, and not
reporting at a resolution that identifies individual properties.

**Q9 — What is left to do?**

Earth Engine integration for green cover and heat island; building height for
the vertical dimension; cross-product validation; predictive modelling; and
ground validation of the candidate zones. The Review 3 milestone of roughly
50% implementation is already met, so the intervening period strengthens
evidence rather than catching up.

---

## 4. Presentation structure — suggested 12 slides

| # | Slide | Content |
|---|---|---|
| 1 | Title | Project, city, team, guide |
| 2 | The problem | Three questions current monitoring cannot answer |
| 3 | Why it matters | Infill vs leapfrog cost; the occupancy blind spot |
| 4 | Literature landscape | Six strands, condensed Table 2.1 |
| 5 | Gaps | Table 2.2 — gaps mapped to design responses |
| 6 | Objectives and scope | Including what is deliberately out of scope |
| 7 | Architecture | Figure 3.1 |
| 8 | Core method | Figure 3.3 — learned expectation, not threshold |
| 9 | Data sources | Table 3.2 with the dual-path rationale |
| 10 | Feasibility evidence | Preliminary Varanasi results |
| 11 | Risks and ethics | Risk register; misuse analysis; AI disclosure |
| 12 | Plan | Figure 4.1 timeline |

**Opening line worth using:** *"Varanasi's built-up area grew 32% while its
population grew 14%. We built a system to find out where that land went — and
whether anyone is using it."*

**Two things to say explicitly, unprompted:** that the ghost figure is an
upper bound, and that AI assistance was used and is disclosed in Appendix A.
Volunteering both is far stronger than being asked.
