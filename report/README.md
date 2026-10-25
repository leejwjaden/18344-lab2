# Lab 2 LaTeX report

Open `main.pdf` for the compiled 10-page report or `main.tex` to edit it.
The project is also compatible with the Codex built-in LaTeX editor.

The report covers Tasks 1--4, with seven vector figures, the 20-design catalog,
Pareto and sensitivity analysis, implementation details, and Destiny-based
implementability discussion. Task 1 AMAT is derived from corrected L1 counters
and Destiny latencies. Task 2's legacy and corrected datasets are explicitly
separated: corrected four-policy runs at two more geometries remain necessary
for full compliance with that experimental requirement.

## Rebuild

From the repository root:

```bash
python3 -m pip install matplotlib
python3 report/build_figures.py
cd report
pdflatex main.tex
pdflatex main.tex
```

Alternatively, run `tectonic main.tex` from this folder. The figure generator
uses the committed `results/` files and does not launch benchmarks. It writes
PDF/PNG figures, generated LaTeX tables, derived Task 1 data, and an analysis
JSON under this project. Existing source experiment files are not modified.

The report was compiled with Tectonic and the built-in LaTeX compiler. All pages
were rendered and visually reviewed. The figure generator requires matplotlib;
no external plotting tools are required to compile the already-generated source.

## Evidence

Primary session: `../results/task4/session-3973386ea9622d3cee1b/`.
Legacy Task 2 source: `../results/task1-3/task2/task2.csv`.
Handout: `../18344-f25-lab2-memoryhierarchy.pdf`.

Do not remove the Task 2 evidence caveat unless the missing experiments have
actually been collected and incorporated.
