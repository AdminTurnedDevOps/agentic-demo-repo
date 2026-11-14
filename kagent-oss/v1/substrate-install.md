

## Binary

Pull the latest `kubectl ate` binary

```bash
gh release download v1.0.1 \
  --repo kagent-dev/substrate \
  --pattern 'kubectl-ate-darwin-arm64*'
```

Ensure it's on your path:

```bash
mkdir -p "$HOME/.local/bin"
install -m 0755 kubectl-ate-darwin-arm64 "$HOME/.local/bin/kubectl-ate"
export PATH="$HOME/.local/bin:$PATH"
```

## Install

Create an env var for your clusters context

```bash
CTX="my-test-cluster"
```

Launch the wizard

```bash
kubectl ate --context "$CTX" install
```