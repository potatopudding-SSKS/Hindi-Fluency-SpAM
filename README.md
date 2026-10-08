# Hindi-Fluency-SpAM
Data, Code and Analyses for the Fluency-SpAM experiment.

## Layout

- `Experiment/`: the experiment (Streamlit + MongoDB).
- `Data/data_cleaning.ipynb`: fetches the data from MongoDB, anonymises and cleans it. Identifiable raw data goes in `Data/raw/`, which is gitignored. Romanised words are mapped to Devanagari with `Data/transliteration_key.json`.
- `Analyses/analysis.ipynb`: semantic and phonological similarity analyses, plus an English vs Hindi embedding comparison.

## Setup

Requires Python 3.14 and graph-tool installed as a system package (Arch: `python-graph-tool`). graph-tool is not on PyPI, so the venv needs access to system site-packages:

```bash
uv venv --python /usr/bin/python3.14 --system-site-packages
uv sync
```

Open the notebooks with the `.venv` kernel. `Analyses/` also needs the Hindi fastText model `cc.hi.300.bin` (~7 GB), which is downloaded automatically if missing.
