# python/ — local packaging layout

This folder is the **stable local packaging face** for the existing NL-to-SQL engine.

## Important

- The real engine lives in `src/nlq/`.
- **Do not rewrite** NL-to-SQL here.
- BU onboarding must not add hard-coded routing in this package.

## Layout

```text
python/
├── README.md                 # this file
├── notebooks/
│   └── README.md             # points to ../notebooks
└── nl_to_sql/
    ├── README.md             # integration boundary
    └── bridge.py             # thin re-exports → src/nlq
```

## Usage

```powershell
$env:PYTHONPATH = "src;."   # include project root so `python.nl_to_sql` resolves
py -3 -c "from python.nl_to_sql.bridge import ask; print(ask('How many cases were opened last month?'))"
```

Or from a notebook with project root on `PYTHONPATH`.
