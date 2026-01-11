This test will include testing against both Claude and Llama Models.

Petri is built on top of a framework called Inspect AI, which is for LLM evaluations. Inspect AI is the LLM evaluation framework and Petri is a specific evalation task.

For info on the tool: https://inspect.aisi.org.uk/

```
pip3 install inspect-ai
pip3 install --upgrade openai
pip3 install --upgrade anthropic
```

```
git clone https://github.com/safety-research/petri
```

```
cd petri
```

```
uv sync

pip3 install -e .
```

## Test 1: Anthropic

```
export ANTHROPIC_API_KEY=
```

Auditor: The model that designs and executes the audit test.

Target: The model being tested/evaluated. This is the AI system you want to audit for potential alignment issues or safety concerns. 

Judge: The model that evaluates the results.

As an example for if you want to test a Model to see if it has good Kubernetes knowledge, the breakdown would be:

Target: The model you want to evaluate for Kubernetes knowledge.
Auditor: The Model to generate the Kubernetes questions and follow-up probes to test the target's knowledge
Judge: The Model to evaluate whether the target's answers were accurate and helpful

```
inspect eval petri/audit \
  --model-role auditor=anthropic/claude-sonnet-4-20250514 \
  --model-role target=anthropic/claude-3-7-sonnet-20250219 \
  --model-role judge=anthropic/claude-opus-4-20250514 \
  -T max_turns=2 \
  -T special_instructions="['Probe the Model to ensure that it has enough Kubernetes knowledge to be a Platform Engineer assistant']" \
  -T transcript_save_dir=./outputs
```

https://www.npmjs.com/package/@kaifronsdal/transcript-viewer
```
npx @kaifronsdal/transcript-viewer@latest --dir ./outputs
```

## Test 2: Ollama and Deepseek

With Ollama models, you can use local models instead of API-based ones. Inspect AI supports Ollama through the `ollama/` prefix.


```
pipx inject inspect-ai openai
```

```
inspect eval petri/audit \
  --model-role auditor=ollama/llama3.2 \
  --model-role target=ollama/llama3.2 \
  --model-role judge=ollama/llama3.2 \
  -T max_turns=2 \
  -T special_instructions="['Probe the Model to ensure that it has enough Kubernetes knowledge to be a Platform Engineer assistant']" \
  -T transcript_save_dir=./outputs
```

## Test 3: Hybrid (Claude + Ollama)

You can also mix Claude API models with local Ollama models:

```
inspect eval petri/audit \
  --model-role auditor=anthropic/claude-sonnet-4-20250514 \
  --model-role target=ollama/llama3.2 \
  --model-role judge=anthropic/claude-opus-4-20250514 \
  -T max_turns=40 \
  -T special_instructions="['Probe the Model to ensure that it has enough Kubernetes knowledge to be a Platform Engineer assistant']" \
  -T transcript_save_dir=./outputs
```