#!/bin/bash
# Demo Runner Script
# Interactive script to run the self-healing demo

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Self-Healing Kubernetes Cluster Demo                     ║${NC}"
echo -e "${BLUE}║     Powered by kagent + agentgateway                         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"

# Function to wait for user
pause() {
    echo -e "\n${YELLOW}Press Enter to continue...${NC}"
    read
}

# Step 1: Show current state
echo -e "\n${GREEN}Step 1: Current Cluster State${NC}"
echo "Checking httpbin deployment status..."
kubectl get pods -n demo -l app=httpbin
kubectl get deployment httpbin -n demo
pause

# Step 2: Inject failure
echo -e "\n${RED}Step 2: Injecting Failure!${NC}"
echo "Choose a chaos scenario:"
echo "  1) CrashLoopBackOff (bad command)"
echo "  2) OOMKill (memory pressure)"
echo "  3) Scale to Zero (no replicas)"
echo "  4) Bad ConfigMap (startup failure)"
read -p "Enter choice [1-4]: " choice

case $choice in
    1) bash "$SCRIPT_DIR/chaos-scenarios/inject-crashloop.sh" ;;
    2) bash "$SCRIPT_DIR/chaos-scenarios/inject-oom.sh" ;;
    3) bash "$SCRIPT_DIR/chaos-scenarios/inject-scale-down.sh" ;;
    4) bash "$SCRIPT_DIR/chaos-scenarios/inject-bad-config.sh" ;;
    *) echo "Invalid choice"; exit 1 ;;
esac

pause

# Step 3: Watch self-healing
echo -e "\n${GREEN}Step 3: Watching Self-Healing in Action${NC}"
echo "The agent should detect the issue within 1 minute..."
echo ""
echo "Current pod status (refreshing every 10s):"
echo "Press Ctrl+C to stop watching"
echo ""

# Watch pods until user interrupts
trap 'echo -e "\n${YELLOW}Stopped watching${NC}"' INT
for i in {1..30}; do
    clear
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║     Self-Healing Demo - Watch Mode (Check $i/30)              ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}=== Pod Status ===${NC}"
    kubectl get pods -n demo -l app=httpbin
    echo ""
    echo -e "${BLUE}=== Deployment Status ===${NC}"
    kubectl get deployment httpbin -n demo
    echo ""
    echo -e "${BLUE}=== Recent Events ===${NC}"
    kubectl get events -n demo --sort-by='.lastTimestamp' 2>/dev/null | tail -10
    sleep 10
done
trap - INT

# Step 4: Verify healing
echo -e "\n${GREEN}Step 4: Verifying Cluster Health${NC}"
kubectl get pods -n demo -l app=httpbin
kubectl get deployment httpbin -n demo

echo -e "\n${GREEN}Demo Complete!${NC}"
echo "Check the agentgateway UI for the full trace of agent actions."
