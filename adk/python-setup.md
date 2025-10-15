```
python3.11 -m venv .venv
```

```
source .venv/bin/activate
```

```
pip install google-adk
```

```
adk create pyagenttest
```

```
pip install -r adk/pyagenttest/requirements.txt
```

Run of the CLI
```
cd adk/pyagenttest && adk run pyagenttest
```

Run on the UI
```
cd pyagenttest && adk web
```