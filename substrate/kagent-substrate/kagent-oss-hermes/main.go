package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"strings"

	a2atype "github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/kagent-dev/kagent/go/adk/pkg/app"
	runtimea2a "github.com/kagent-dev/kagent/go/harness/runtime/a2a"
	"github.com/kagent-dev/kagent/go/harness/runtime/continuation"
	"github.com/kagent-dev/kagent/go/pkg/logging"
)

const (
	configEnv    = "KAGENT_CONFIG_JSON"
	agentCardEnv = "KAGENT_AGENT_CARD_JSON"
	dataDir      = "/data"
	workspaceDir = "/data/workspace"
	privatePort  = "80"
)

func main() {
	check := flag.Bool("check", false, "validate configuration and Hermes ACP startup, then exit")
	flag.Parse()
	logger, err := logging.NewFromEnv(os.Stderr)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	ctx := logging.IntoContext(context.Background(), logger)
	if err := run(ctx, logger, *check); err != nil {
		logger.ErrorContext(ctx, "Hermes Harness stopped", "error", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, logger *slog.Logger, check bool) error {
	configJSON, err := requiredEnvironment(configEnv)
	if err != nil {
		return err
	}
	agentCardJSON, err := requiredEnvironment(agentCardEnv)
	if err != nil {
		return err
	}

	var card a2atype.AgentCard
	if err := json.Unmarshal(agentCardJSON, &card); err != nil {
		return fmt.Errorf("decode Agent Card: %w", err)
	}
	if strings.TrimSpace(card.Name) == "" {
		return fmt.Errorf("Agent Card name is required")
	}

	if err := materializeHermesConfig(configJSON, dataDir, workspaceDir); err != nil {
		return err
	}
	runner := newHermesRunner(logger, []string{"hermes", "acp"}, dataDir, workspaceDir)
	defer runner.Close()
	if check {
		if err := runner.Check(ctx); err != nil {
			return fmt.Errorf("check Hermes runtime: %w", err)
		}
		return nil
	}
	store, err := continuation.New(dataDir+"/adapter", "hermes", validateSessionID)
	if err != nil {
		return fmt.Errorf("create continuation store: %w", err)
	}
	executor, err := runtimea2a.New(runner, store)
	if err != nil {
		return fmt.Errorf("create A2A executor: %w", err)
	}
	application, err := app.New(app.AppConfig{
		AgentCard: card,
		Port:      privatePort,
		AppName:   card.Name,
		Logger:    logger,
	}, executor)
	if err != nil {
		return fmt.Errorf("construct private A2A app: %w", err)
	}
	return application.Run()
}

func requiredEnvironment(name string) ([]byte, error) {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return nil, fmt.Errorf("%s is required", name)
	}
	return []byte(value), nil
}

func validateSessionID(id string) error {
	if strings.TrimSpace(id) == "" {
		return fmt.Errorf("Hermes session ID is empty")
	}
	return nil
}
