# Lab 2 LaTeX report

`main.pdf` is the compiled report; `main.tex` is the editable source.
The report covers Tasks 1--4, including corrected single-level measurements,
all four policies at three geometries on both benchmarks, the 20-design search,
Pareto and sensitivity analysis, and Destiny-based implementability analysis.

## Rebuild

From the repository root:

```bash
python3 -m pip install matplotlib
python3 report/build_figures.py
cd report
pdflatex main.tex
pdflatex main.tex
```

Tectonic is also supported. Figures are vector PDFs with PNG previews.
The generator reads committed results; it never launches benchmarks.

## Evidence

- Corrected Tasks 1/2: `../results/task1-3-corrected/session-1a552b2c84d04b334d9e/`
- Two-level Tasks 3/4: `../results/task4/session-3973386ea9622d3cee1b/`
- Handout: `../18344-f25-lab2-memoryhierarchy.pdf`

The corrected export includes `validation.json`, raw counters, completion records,
commands, hardware models, and per-part plots. Legacy tree-PLRU data is not used
in the report. Report conclusions are limited to the documented test workloads,
single-run measurements, and demand-only cache model.
