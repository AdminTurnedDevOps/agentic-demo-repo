```
python3.11 -m venv .venv
```

```
source .venv/bin/activate
```

```
pip install google-adk

pip install litellm
```

```
export ANTHROPIC_API_KEY=
```

```
pip install -r adk/pyagenttest/requirements.txt
```

Run on the CLI
```
cd adk/pyagenttest && adk run pyagenttest
```

Run on the UI
```
adk web
```