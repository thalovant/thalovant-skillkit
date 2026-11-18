# Quick facts: thalovant-skillkit

Read from the package source and metadata for the 0.38.1 handback repair (2026-11-18).

| Fact | Value |
| :--- | :--- |
| Package | `thalovant-skillkit` |
| Version | 0.38.1 (`thalovant_skillkit/version.py`, `pyproject.toml`) |
| Python | 3.11 or newer (classifiers 3.11 to 3.14) |
| Licence | Apache-2.0 |
| Build backend | `setuptools>=68` |
| Entry points | console script `thalovant-skillkit` = `thalovant_skillkit.cli:main`; no `opm.*` plugin entry points |
| CLI commands | `new`, `locales`, `check`, `check-artifacts` (`thalovant_skillkit/cli.py`) |
| Runtime dependencies | `requests`, `ovos-utils`, `ovos-spec-tools`, `langcodes`, `ovos-workshop`, `thalovant-languages>=0.3.0`, `ovos-date-parser`, `babel`, `model2vec`, `tokenizers<1` (kept below 1 on purpose, see the comment in `pyproject.toml`), `numpy` |
| Extras | `testing` (ovoscope, ovos-bus-client, pytest, pytest-timeout); `skill` and `fleet` are empty names kept for old pins |
| Handback topic | `handback._utterance_topic`: loaded core entry topic; standalone processes follow workshop; one replay with original request correlation |
| Main modules | `skill.py` (base class), `safety.py` (URL guard, cleaner), `device.py` (the device gate), `handback.py` (`pass_on`), `fallback.py`, `fleet.py`, `moments.py`, `records.py`, `storage.py`, `testing.py`, `testing_ovos.py` |
| Vendored in | ovos-runtime-image `v1.25.0` as a `pin` wheel (`runtime-wheels/wheels.manifest`) |
| Tests | `test/` (66 files); run `python -m pytest -q` |
| Documentation | `docs/reference.md`, `docs/records.md`, `docs/performance.md`, `docs/testing-audio.md`; public: https://docs.thalovant.com/developers/writing-a-skill |
| Changelog | `CHANGELOG.md` |
