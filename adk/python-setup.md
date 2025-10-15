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
<<<<<<< HEAD
pip install -r adk/pyagenttest/requirements.txt
=======
adk create pyagent
>>>>>>> b65c90f3f145da40807634084b9111d4dff3b050
```

Run on the CLI
```
<<<<<<< HEAD
cd adk/pyagenttest && adk run pyagenttest
=======
cd adk && adk run pyagent/
```

If you're having trouble with the above, try:
```
source .venv/bin/activate
pip install --force-reinstall google-adk
adk run pyagent/
>>>>>>> b65c90f3f145da40807634084b9111d4dff3b050
```

Run on the UI
```
adk web
```