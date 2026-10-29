# Vitals

Project page: https://gbogdev.github.io/Vitals/

Desktop utility (Python, PySide6) for inspecting local system resource usage and investigating application logs. Everything stays on your machine; nothing is uploaded.

## Features

- **Monitoring:** CPU, memory, disk, network throughput, top processes; configurable refresh interval; bounded in-memory history with line charts. Unreadable metrics (e.g. permission denied) show as `n/a`.
- **Logs:** import text logs (parsed incrementally in a background thread), search (plain/regex), filter by severity, time range and source, group recurring errors, view surrounding entries, export filtered results (CSV/JSON/text). Parsing rules are regexes in the config file.
- **Diagnostics:** configurable threshold rules for sustained high CPU/memory/disk usage and recurring log errors. These are simple threshold comparisons on measured values. An alert means a rule matched; it is not a confirmed fault.
- **Reports:** export a text or JSON report of measured aggregates, alerts and log summary.

Config: `%APPDATA%\Vitals\config.json` (override with `VITALS_CONFIG`). Missing keys use defaults; see `vitals/config.py`.

## Install

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m vitals
```

## Test

```
pip install pytest
python -m pytest
```

Tests cover log parsing, filtering/grouping, diagnostic rules, metric aggregation and report generation. The GUI has not been systematically tested; it was only smoke-launched headlessly on one Windows machine.

## Windows packaging

```
pip install pyinstaller
pyinstaller --noconsole --name Vitals --icon assets/vitals.ico run_vitals.py
```

The executable is written to `dist\Vitals\`. The packaged build has not been tested here.

## License

GNU General Public License v3.0 only. See [LICENSE](LICENSE).

## Notes

Parts of the code were written with help from an AI coding assistant; all code is reviewed and maintained by the repository owner.
