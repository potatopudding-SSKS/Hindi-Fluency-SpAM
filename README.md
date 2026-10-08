# Hindi-Fluency-SpAM
Data, Code and Analyses for the Fluency-SpAM experiment.

## Layout

- `Experiment/`: the experiment (Streamlit + MongoDB).
- `Data/data_cleaning.ipynb`: fetches the data from MongoDB, anonymises and cleans it.
- Romanised words are mapped to Devanagari with `Data/transliteration_key.json` which is manually created.
- `Analyses/analysis.ipynb`: semantic and phonological similarity analyses.

## Setup

Open the notebooks with the `.venv` kernel. `Analyses/` also needs the Hindi fastText model `cc.hi.300.bin` (~7 GB), which is downloaded automatically if missing.
