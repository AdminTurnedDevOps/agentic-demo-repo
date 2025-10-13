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
adk create pyagent
```

Run on the CLI
```
cd adk && adk run pyagent/
```

If you're having trouble with the above, try:
```
source .venv/bin/activate
pip install --force-reinstall google-adk
adk run pyagent/
```

Run on the UI
```
adk web
```