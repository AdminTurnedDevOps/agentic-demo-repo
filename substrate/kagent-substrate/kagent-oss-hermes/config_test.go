package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestMaterializeHermesConfig(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	workspace := filepath.Join(root, "workspace")
	raw := []byte(`{"model":{"type":"openai","model":"gpt-4.1-mini","base_url":"https://api.openai.com/v1"},"instruction":"Be concise."}`)
	if err := materializeHermesConfig(raw, root, workspace); err != nil {
		t.Fatal(err)
	}
	contents, err := os.ReadFile(filepath.Join(root, "hermes", "config.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	text := string(contents)
	for _, expected := range []string{
		"default: gpt-4.1-mini", "provider: openai", "base_url: https://api.openai.com/v1",
		"max_tokens: 32768", "key_env: OPENAI_API_KEY", "api_mode: chat_completions", "system_prompt: Be concise.",
	} {
		if !strings.Contains(text, expected) {
			t.Fatalf("configuration does not contain %q:\n%s", expected, text)
		}
	}
}

func TestMaterializeHermesConfigRejectsUnsupportedProvider(t *testing.T) {
	t.Parallel()
	err := materializeHermesConfig([]byte(`{"model":{"type":"anthropic","model":"claude"}}`), t.TempDir(), t.TempDir())
	if err == nil || !strings.Contains(err.Error(), "only OpenAI") {
		t.Fatalf("expected unsupported provider error, got %v", err)
	}
}
