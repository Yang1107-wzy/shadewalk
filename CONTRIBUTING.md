# Contributing

Thanks for your interest! Issues and pull requests are welcome, especially new data sources (tree canopy, terrain), validation against field measurements, and support for other cities.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,lst,docs]"
pytest -q                      # offline unit tests
ruff check . && ruff format .  # lint + format
mypy src/shadewalk             # type check
mkdocs serve                   # docs preview
```

Tests must not hit the network. Use synthetic fixtures (`tests/conftest.py`). Tests that need real downloads go behind `@pytest.mark.network`, which is deselected by default.

## Guidelines

* Keep geometry in EPSG:2326 internally, and convert to WGS84 only at the I/O boundaries.
* Every new data source needs an entry in `DATA_ATTRIBUTION.md` and should go through `shadewalk.data.cache.cached_get` so that downloads are logged with their checksums.
* Report numbers in docs only if they come from a script in `scripts/` that anyone can rerun.
