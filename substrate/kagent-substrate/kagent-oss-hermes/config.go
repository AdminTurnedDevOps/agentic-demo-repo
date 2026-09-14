package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

type kagentConfig struct {
	Model struct {
		Type                string `json:"type"`
		Model               string `json:"model"`
		BaseURL             string `json:"base_url"`
		MaxTokens           int    `json:"max_tokens"`
		MaxCompletionTokens int    `json:"max_completion_tokens"`
	} `json:"model"`
	Instruction string `json:"instruction"`
}

type hermesConfig struct {
	Model struct {
		Default   string `yaml:"default"`
		Provider  string `yaml:"provider"`
		BaseURL   string `yaml:"base_url,omitempty"`
		MaxTokens int    `yaml:"max_tokens"`
	} `yaml:"model"`
	Providers map[string]hermesProvider `yaml:"providers"`
	Agent     struct {
		SystemPrompt string `yaml:"system_prompt,omitempty"`
	} `yaml:"agent"`
	Terminal struct {
		Cwd string `yaml:"cwd"`
	} `yaml:"terminal"`
}

type hermesProvider struct {
	BaseURL string `yaml:"base_url"`
	KeyEnv  string `yaml:"key_env"`
	APIMode string `yaml:"api_mode"`
	Model   string `yaml:"model"`
}

func materializeHermesConfig(raw []byte, dataDir, workspace string) error {
	var input kagentConfig
	if err := json.Unmarshal(raw, &input); err != nil {
		return fmt.Errorf("decode %s: %w", configEnv, err)
	}
	if input.Model.Type != "openai" {
		return fmt.Errorf("Hermes BYO runtime currently supports only OpenAI ModelConfig, got %q", input.Model.Type)
	}
	if strings.TrimSpace(input.Model.Model) == "" {
		return fmt.Errorf("OpenAI model name is required")
	}

	var output hermesConfig
	output.Model.Default = input.Model.Model
	output.Model.Provider = "openai"
	output.Model.BaseURL = input.Model.BaseURL
	output.Model.MaxTokens = input.Model.MaxCompletionTokens
	if output.Model.MaxTokens == 0 {
		output.Model.MaxTokens = input.Model.MaxTokens
	}
	if output.Model.MaxTokens == 0 {
		output.Model.MaxTokens = 32768
	}
	if output.Model.BaseURL == "" {
		output.Model.BaseURL = "https://api.openai.com/v1"
	}
	output.Providers = map[string]hermesProvider{"openai": {
		BaseURL: output.Model.BaseURL,
		KeyEnv:  "OPENAI_API_KEY",
		APIMode: "chat_completions",
		Model:   output.Model.Default,
	}}
	output.Agent.SystemPrompt = input.Instruction
	output.Terminal.Cwd = workspace

	home := filepath.Join(dataDir, "hermes")
	if err := os.MkdirAll(home, 0o700); err != nil {
		return fmt.Errorf("create Hermes home: %w", err)
	}
	if err := os.MkdirAll(workspace, 0o700); err != nil {
		return fmt.Errorf("create Hermes workspace: %w", err)
	}
	contents, err := yaml.Marshal(output)
	if err != nil {
		return fmt.Errorf("marshal Hermes configuration: %w", err)
	}
	if err := os.WriteFile(filepath.Join(home, "config.yaml"), contents, 0o600); err != nil {
		return fmt.Errorf("write Hermes configuration: %w", err)
	}
	return nil
}
