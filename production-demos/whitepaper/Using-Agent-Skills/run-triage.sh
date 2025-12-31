#!/bin/bash
# Execution Workflow: CrashLoopBackOff Triage Demonstration
# Shows how the autonomous SRE agent uses skills to diagnose pod failures

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Available failure scenarios
declare -A SCENARIOS=(
    ["config"]="api-server-missing-env"
    ["memory"]="memory-hog-oom"
    ["network"]="web-app-no-db"
    ["health"]="app-bad-healthcheck"
    ["rbac"]="secret-reader-no-perms"
)

print_header() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}${BOLD}     Self-Healing Infrastructure: CrashLoopBackOff Triage      ${NC}${CYAN}║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_info() {
    echo -e "${CYAN}[i]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_agent() {
    echo -e "${MAGENTA}[Agent]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    print_info "Checking prerequisites..."

    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl is not installed"
        exit 1
    fi

    if ! command -v kagent &> /dev/null; then
        print_warning "kagent CLI not found. Agent invocation will be simulated."
        KAGENT_AVAILABLE=false
    else
        KAGENT_AVAILABLE=true
    fi

    if ! kubectl cluster-info &> /dev/null; then
        print_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi

    print_status "Prerequisites verified"
}

# Deploy the skill
deploy_skill() {
    print_info "Deploying k8s-crash-triage skill..."

    kubectl create namespace kagent --dry-run=client -o yaml | kubectl apply -f -
    kubectl apply -f "${SCRIPT_DIR}/triage-skill.yaml"

    print_status "Triage skill deployed"
}

# Deploy the agent
deploy_agent() {
    print_info "Deploying autonomous-sre agent with triage skill..."

    kubectl apply -f "${SCRIPT_DIR}/sre-triage-agent.yaml"

    print_status "Autonomous SRE agent deployed"
}

# Deploy broken applications
deploy_broken_apps() {
    local scenario=${1:-all}

    print_info "Deploying broken application(s)..."

    kubectl apply -f "${SCRIPT_DIR}/broken-app.yaml"

    print_status "Broken applications deployed to 'broken-apps' namespace"

    # Wait for pods to enter CrashLoopBackOff
    print_info "Waiting for pods to enter CrashLoopBackOff state..."
    sleep 15

    show_broken_pods
}

# Show broken pods status
show_broken_pods() {
    echo ""
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}  PODS IN CRASHLOOPBACKOFF${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    kubectl get pods -n broken-apps -o wide 2>/dev/null || echo "No pods found"

    echo ""
    echo -e "${YELLOW}Available scenarios for triage:${NC}"
    echo "  1. config  - api-server-missing-env (Missing DATABASE_URL)"
    echo "  2. memory  - memory-hog-oom (OOMKilled - exit code 137)"
    echo "  3. network - web-app-no-db (Dependency service unreachable)"
    echo "  4. health  - app-bad-healthcheck (Liveness probe failure)"
    echo "  5. rbac    - secret-reader-no-perms (RBAC permission denied)"
    echo ""
}

# Select a scenario for triage
select_scenario() {
    local scenario=$1
    local deployment_name=""

    case $scenario in
        config|1)
            deployment_name="api-server-missing-env"
            ;;
        memory|2)
            deployment_name="memory-hog-oom"
            ;;
        network|3)
            deployment_name="web-app-no-db"
            ;;
        health|4)
            deployment_name="app-bad-healthcheck"
            ;;
        rbac|5)
            deployment_name="secret-reader-no-perms"
            ;;
        *)
            print_error "Unknown scenario: $scenario"
            echo "Valid options: config, memory, network, health, rbac (or 1-5)"
            exit 1
            ;;
    esac

    echo "$deployment_name"
}

# Invoke the agent to triage a specific pod
invoke_agent() {
    local scenario=${1:-config}
    local deployment_name=$(select_scenario "$scenario")

    # Get the pod name
    local pod_name=$(kubectl get pods -n broken-apps -l app=${deployment_name%-*} -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

    if [[ -z "$pod_name" ]]; then
        # Fallback to deployment name pattern
        pod_name=$(kubectl get pods -n broken-apps --no-headers 2>/dev/null | grep "$deployment_name" | awk '{print $1}' | head -1)
    fi

    if [[ -z "$pod_name" ]]; then
        print_error "Could not find pod for deployment: $deployment_name"
        print_info "Listing available pods:"
        kubectl get pods -n broken-apps
        exit 1
    fi

    echo ""
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${MAGENTA}  INVOKING AUTONOMOUS SRE AGENT${NC}"
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    print_info "Target: broken-apps/${pod_name}"
    print_info "Scenario: ${scenario} (${deployment_name})"
    echo ""

    local prompt="A pod named '${pod_name}' in namespace 'broken-apps' is stuck in CrashLoopBackOff. Please investigate and provide a Root Cause Analysis report with recommended fix."

    if [[ "$KAGENT_AVAILABLE" == "true" ]]; then
        kagent invoke autonomous-sre \
            --namespace kagent \
            --prompt "$prompt" \
            --timeout 180s
    else
        simulate_agent_response "$scenario" "$pod_name" "$deployment_name"
    fi
}

# Simulate agent response for demonstration
simulate_agent_response() {
    local scenario=$1
    local pod_name=$2
    local deployment_name=$3

    print_agent "Detected CrashLoopBackOff for pod: ${pod_name}"
    print_agent "Invoking k8s-crash-triage skill..."
    echo ""
    sleep 1

    # Step 1: Event Inspection
    echo -e "${BLUE}Step 1: Event Inspection${NC}"
    echo "  Executing: kubectl get events --field-selector involvedObject.name=${pod_name} -n broken-apps"
    sleep 1
    kubectl get events --field-selector involvedObject.name=${pod_name} -n broken-apps --sort-by='.lastTimestamp' 2>/dev/null | head -10 || echo "  (Events retrieved)"
    echo ""
    sleep 1

    # Step 2: Log Extraction
    echo -e "${BLUE}Step 2: Log Extraction${NC}"
    echo "  Executing: kubectl logs ${pod_name} -n broken-apps --tail=20"
    sleep 1
    kubectl logs ${pod_name} -n broken-apps --tail=20 2>/dev/null || kubectl logs ${pod_name} -n broken-apps --previous --tail=20 2>/dev/null || echo "  (Logs retrieved)"
    echo ""
    sleep 1

    # Step 3: Network Validation
    echo -e "${BLUE}Step 3: Network Validation${NC}"
    echo "  Executing: kubectl get endpoints -n broken-apps"
    sleep 1
    kubectl get endpoints -n broken-apps 2>/dev/null || echo "  (Endpoints checked)"
    echo ""
    sleep 1

    # Generate Root Cause Report based on scenario
    generate_rca_report "$scenario" "$pod_name" "$deployment_name"
}

# Generate the Root Cause Analysis report
generate_rca_report() {
    local scenario=$1
    local pod_name=$2
    local deployment_name=$3

    local root_cause=""
    local evidence_event=""
    local evidence_log=""
    local evidence_network=""
    local fix_description=""
    local fix_command=""

    case $scenario in
        config)
            root_cause="CONFIGURATION"
            evidence_event="Container exited with code 1"
            evidence_log="FATAL ERROR: Required environment variable DATABASE_URL is not set"
            evidence_network="N/A - Not a network issue"
            fix_description="Add the missing DATABASE_URL environment variable to the deployment"
            fix_command="kubectl set env deployment/${deployment_name} DATABASE_URL=\"postgresql://user:pass@db-host:5432/mydb\" -n broken-apps"
            ;;
        memory)
            root_cause="MEMORY"
            evidence_event="OOMKilled - Container exceeded memory limit (exit code 137)"
            evidence_log="Allocating memory for data processing... Killed"
            evidence_network="N/A - Not a network issue"
            fix_description="Increase memory limit from 32Mi to at least 256Mi"
            fix_command="kubectl patch deployment ${deployment_name} -n broken-apps --type=json -p='[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/resources/limits/memory\",\"value\":\"256Mi\"}]'"
            ;;
        network)
            root_cause="DEPENDENCY"
            evidence_event="Container exited with code 1 after connection failures"
            evidence_log="ERROR: Connection refused - postgres-db service not reachable"
            evidence_network="No endpoints found for postgres-db service"
            fix_description="Deploy the postgres-db service or update DB_HOST to point to existing database"
            fix_command="kubectl create service clusterip postgres-db --tcp=5432:5432 -n broken-apps"
            ;;
        health)
            root_cause="HEALTH CHECK"
            evidence_event="Liveness probe failed: HTTP probe failed with statuscode: connection refused"
            evidence_log="Application running but health endpoint not implemented"
            evidence_network="N/A - Application is running internally"
            fix_description="Fix the liveness probe path or implement /healthz endpoint in application"
            fix_command="kubectl patch deployment ${deployment_name} -n broken-apps --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/template/spec/containers/0/livenessProbe\"}]'"
            ;;
        rbac)
            root_cause="RBAC"
            evidence_event="Container exited with code 1"
            evidence_log="FATAL ERROR: Failed to read secret - forbidden"
            evidence_network="N/A - Not a network issue"
            fix_description="Create RoleBinding to allow ServiceAccount to read secrets"
            fix_command="kubectl create rolebinding secret-reader-binding --clusterrole=view --serviceaccount=broken-apps:restricted-sa -n broken-apps"
            ;;
    esac

    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}                  ROOT CAUSE ANALYSIS REPORT${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "Pod: ${BOLD}broken-apps/${pod_name}${NC}"
    echo -e "Status: ${RED}CrashLoopBackOff${NC}"
    echo -e "Analysis Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo ""
    echo -e "┌─────────────────────────────────────────────────────────────┐"
    echo -e "│ ROOT CAUSE: ${BOLD}${root_cause}${NC}$(printf '%*s' $((42 - ${#root_cause})) '')│"
    echo -e "├─────────────────────────────────────────────────────────────┤"
    echo -e "│ ${evidence_log:0:59}│"
    echo -e "└─────────────────────────────────────────────────────────────┘"
    echo ""
    echo -e "${YELLOW}EVIDENCE:${NC}"
    echo ""
    echo -e "  Step 1 (Events):"
    echo -e "    • ${evidence_event}"
    echo ""
    echo -e "  Step 2 (Logs):"
    echo -e "    • ${evidence_log}"
    echo ""
    echo -e "  Step 3 (Network):"
    echo -e "    • ${evidence_network}"
    echo ""
    echo -e "${GREEN}RECOMMENDED FIX:${NC}"
    echo ""
    echo -e "  ${fix_description}"
    echo ""
    echo -e "  ${CYAN}Command:${NC}"
    echo -e "  \$ ${fix_command}"
    echo ""
    echo -e "${BOLD}CONFIDENCE: High${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Apply the fix for a scenario
apply_fix() {
    local scenario=${1:-config}
    local deployment_name=$(select_scenario "$scenario")

    echo ""
    print_info "Applying fix for scenario: ${scenario}"

    case $scenario in
        config)
            kubectl set env deployment/${deployment_name} DATABASE_URL="postgresql://user:pass@db-host:5432/mydb" -n broken-apps
            ;;
        memory)
            kubectl patch deployment ${deployment_name} -n broken-apps --type=json \
                -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"256Mi"}]'
            ;;
        network)
            # Create a dummy service to satisfy the dependency
            kubectl create service clusterip postgres-db --tcp=5432:5432 -n broken-apps 2>/dev/null || true
            ;;
        health)
            kubectl patch deployment ${deployment_name} -n broken-apps --type=json \
                -p='[{"op":"remove","path":"/spec/template/spec/containers/0/livenessProbe"}]'
            ;;
        rbac)
            kubectl create rolebinding secret-reader-binding \
                --clusterrole=view \
                --serviceaccount=broken-apps:restricted-sa \
                -n broken-apps 2>/dev/null || true
            ;;
    esac

    print_status "Fix applied. Waiting for pod to recover..."
    sleep 10
    kubectl get pods -n broken-apps | grep "$deployment_name"
}

# Cleanup
cleanup() {
    print_info "Cleaning up resources..."

    kubectl delete -f "${SCRIPT_DIR}/broken-app.yaml" --ignore-not-found 2>/dev/null || true
    kubectl delete -f "${SCRIPT_DIR}/sre-triage-agent.yaml" --ignore-not-found 2>/dev/null || true
    kubectl delete -f "${SCRIPT_DIR}/triage-skill.yaml" --ignore-not-found 2>/dev/null || true
    kubectl delete namespace broken-apps --ignore-not-found 2>/dev/null || true

    print_status "Cleanup complete"
}

# Show usage
show_usage() {
    echo "Usage: $0 {deploy|triage|fix|status|cleanup} [scenario]"
    echo ""
    echo "Commands:"
    echo "  deploy           - Deploy skill, agent, and broken apps"
    echo "  triage [scenario]- Invoke agent to diagnose a specific scenario"
    echo "  fix [scenario]   - Apply the recommended fix for a scenario"
    echo "  status           - Show current pod status"
    echo "  cleanup          - Remove all deployed resources"
    echo ""
    echo "Scenarios:"
    echo "  config (1)  - Missing environment variable"
    echo "  memory (2)  - OOMKilled (exit code 137)"
    echo "  network (3) - Dependency service unreachable"
    echo "  health (4)  - Liveness probe failure"
    echo "  rbac (5)    - RBAC permission denied"
    echo ""
    echo "Examples:"
    echo "  $0 deploy                    # Deploy everything"
    echo "  $0 triage config             # Triage missing env var scenario"
    echo "  $0 triage 2                  # Triage OOM scenario (by number)"
    echo "  $0 fix memory                # Apply fix for OOM scenario"
}

# Main execution
main() {
    case "${1:-}" in
        deploy)
            print_header
            check_prerequisites
            deploy_skill
            deploy_agent
            deploy_broken_apps
            echo ""
            print_status "Deployment complete!"
            print_info "Run './run-triage.sh triage <scenario>' to invoke the agent"
            ;;

        triage)
            print_header
            invoke_agent "${2:-config}"
            ;;

        fix)
            apply_fix "${2:-config}"
            ;;

        status)
            show_broken_pods
            ;;

        cleanup)
            cleanup
            ;;

        *)
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
