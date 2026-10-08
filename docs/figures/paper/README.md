# Publication figures

Four figures for the image model, sized for an IEEE two-column page (7.16 in text
width; Figure 3 fits one 3.5 in column). Each comes as:

- **PDF**: vector, fonts embedded. Use this in LaTeX.
- **SVG**: vector, for editing in Inkscape or Illustrator.
- **PNG**: 600 dpi, for Word, slides and Markdown.

Text is set in Times New Roman with STIX maths, to match an IEEE or Elsevier body font.
Every map and number is drawn from the trained model's own outputs. Rebuild all four
with:

```
python scripts/make_paper_figures.py            # all four
python scripts/make_paper_figures.py --only 2   # just the network
```

The script recomputes the ensemble's Figure of Merit on the test period and prints it
(0.1507). If that number ever changes, the rasters on disk have changed too.

## LaTeX

```latex
\begin{figure*}[t]
  \centering
  \includegraphics[width=\textwidth]{fig2_network.pdf}
  \caption{The dual-path network (115,345 parameters). ...}
  \label{fig:network}
\end{figure*}

\begin{figure}[t]
  \centering
  \includegraphics[width=\columnwidth]{fig3_protocol.pdf}
  \caption{Three five-year transitions. ...}
  \label{fig:protocol}
\end{figure}
```

Figures 1, 2 and 4 are full width (`figure*`, `\textwidth`); Figure 3 is one column.

## Captions

**Figure 1 — `fig1_framework`.** Overall framework. (a) Input data, by official
identifier. (b) Dry-season (October–March) Landsat composites are cloud-masked, put on
the OLI reflectance scale (Roy et al., 2016) and resampled with the built-up labels to
the 100 m analysis grid (the 2015 composite is shown). (c) Each training example is a
32 × 32-cell patch with 45 channels; three are shown for one patch: true colour, NDBI
change, and built-up growth over the previous five years. (d) The network of Figure 2,
averaged over five seeds and four rotations, gives a suitability surface *S* (grey:
already urban). (e) A cellular automaton places exactly the observed number of new urban
cells, ranking candidates by 0.65 *S* plus 0.35 times the built-up share within 300 m
(*n*₃₀₀), over eight iterations. (f) The placement is compared with GHS-BUILT-S 2020 on
the held-out 2015→2020 period.

**Figure 2 — `fig2_network`.** The dual-path network (115,345 parameters). Each block is
a feature map: its height and depth show the grid size (32 × 32 or 16 × 16 cells) and
its width the number of channels, given beneath it; hatching marks dropout. The context
path (encoder and decoder) bases each output on a 17 × 17-cell window (1.7 km) but
rebuilds the map from a 16 × 16 grid, so its output is smooth. The per-cell path applies
two 1 × 1 convolutions to each cell's 45 values alone and keeps full resolution. The two
are concatenated and a 1 × 1 convolution gives one logit per cell. The input (true
colour shown) and the output are a real patch from the 2015→2020 test period; grey cells
were already urban.

**Figure 3 — `fig3_protocol`.** Three five-year transitions. Inputs are imagery at
*t* − 5 and *t*, the change between them, and place features at *t*; the label is
whether a cell that is not urban at *t* is urban at *t* + 5. The label windows never
overlap. Weights are fitted on 2010→2015, the stopping epoch is chosen by average
precision on 2000→2005, and 2015→2020 is scored once at the end.

**Figure 4 — `fig4_results`.** Results on the held-out 2015→2020 period. (a) Allocation
outcome of the five-model ensemble over the study area: a hit is a conversion that was
predicted and observed, a miss was observed but not predicted, a false alarm was
predicted but not observed; Figure of Merit = hits / (hits + misses + false alarms).
(b)–(e) The three 4 × 4 km windows with the most observed conversions, chosen by the
reference data and not by how well the model did: the 2015 Landsat composite, the NDBI
change the model was given, its suitability *S* (square-root colour scale; grey: already
urban), and the outcome with each window's own Figure of Merit.

## Before submitting

- The window Figures of Merit in Figure 4 (0.26, 0.35, 0.13) come from three
  high-growth windows, and two of them score above the citywide 0.151. Quote the
  citywide number as the result, not the window numbers.
- The 2015→2020 period was also used to compare model versions during development, so
  it is not a perfectly clean hold-out for choosing between them. Say so in the paper.
