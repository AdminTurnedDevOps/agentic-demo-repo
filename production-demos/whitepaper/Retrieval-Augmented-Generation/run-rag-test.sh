#!/bin/bash
# RAG Demonstration Script: 3 AM Runbook Scenario
# Shows how a kagent agent uses internal knowledge to resolve CSI storage errors

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

print_header() {
    echo ""
    echo -e "${MAGENTA}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║${NC}${BOLD}      3 AM Runbook Scenario - RAG Knowledge Demonstration      ${NC}${MAGENTA}║${NC}"
    echo -e "${MAGENTA}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_scenario() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  SCENARIO: Production Database Pod Failing to Start${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${YELLOW}⚠${NC}  Time: 3:00 AM"
    echo -e "  ${YELLOW}⚠${NC}  Alert: Production database pod stuck in ContainerCreating"
    echo -e "  ${YELLOW}⚠${NC}  Error: CSI driver error (0x99) - Volume attachment state mismatch"
    echo ""
    echo -e "  ${RED}The solution is NOT in public Kubernetes documentation.${NC}"
    echo -e "  ${GREEN}The fix is in our internal runbook: Storage-Failure-SOP-2025.pdf${NC}"
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

    # Check cluster connectivity
    if ! kubectl cluster-info &> /dev/null; then
        print_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi

    print_status "Prerequisites verified"
}

# Initialize the knowledge base
init_knowledge_base() {
    print_info "Initializing knowledge base with internal runbooks..."

    # Create kagent namespace
    kubectl create namespace kagent --dry-run=client -o yaml | kubectl apply -f -

    # Deploy knowledge base resources
    kubectl apply -f "${SCRIPT_DIR}/storage-runbook-knowledge.yaml"

    print_status "Knowledge base initialized with Storage-Failure-SOP-2025 content"

    # Show what's in the knowledge base
    echo ""
    echo -e "${BLUE}Knowledge Base Contents:${NC}"
    echo "  - CSI Error 0x99 resolution procedure"
    echo "  - Required annotation: storage.internal/manual-unlock=true"
    echo "  - VolumeAttachment cleanup procedure"
    echo ""
}

# Deploy the storage expert agent
deploy_agent() {
    print_info "Deploying Storage Expert Agent with RAG capabilities..."

    kubectl apply -f "${SCRIPT_DIR}/storage-sre-agent.yaml"

    # Wait for agent to be ready
    print_info "Waiting for agent to be ready..."
    sleep 5

    print_status "Storage Expert Agent deployed"
}

# Create the chaos scenario
create_chaos() {
    print_info "Creating chaos scenario: Failing PVC with CSI Error 0x99..."

    kubectl apply -f "${SCRIPT_DIR}/failing-pvc.yaml"

    print_status "Chaos scenario deployed"

    # Show the problem
    echo ""
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}  PROBLEM DETECTED${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    echo -e "${YELLOW}Pod Status:${NC}"
    kubectl get pod -n production-app database-pod -o wide 2>/dev/null || echo "  Pod is stuck in Pending/ContainerCreating"

    echo ""
    echo -e "${YELLOW}Events:${NC}"
    echo "  Warning  FailedMount  MountVolume.SetUp failed for volume \"pv-database-storage\":"
    echo "           CSI driver error (0x99): Volume attachment state mismatch"
    echo "           Stale attachment exists on node worker-node-03"
    echo ""

    echo -e "${YELLOW}Stale VolumeAttachment:${NC}"
    kubectl get volumeattachment -l scenario=stale-attachment 2>/dev/null || echo "  csi-abc123-worker-node-03 (STALE)"

    echo ""
    echo -e "${YELLOW}PVC Missing Required Annotation:${NC}"
    echo "  storage.internal/manual-unlock: <NOT SET>"
    echo ""
}

# Invoke the agent to fix the issue
invoke_agent() {
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${MAGENTA}  INVOKING STORAGE EXPERT AGENT${NC}"
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    local prompt="A production database pod in the production-app namespace is stuck in ContainerCreating state. The events show a CSI driver error (0x99) related to volume attachment. The pod name is 'database-pod' and it's trying to mount 'database-storage-claim'. Please diagnose and fix this issue."

    print_info "Sending request to agent..."
    echo ""
    echo -e "${BLUE}User Query:${NC}"
    echo "  $prompt"
    echo ""

    if [[ "$KAGENT_AVAILABLE" == "true" ]]; then
        kagent invoke storage-expert \
            --namespace kagent \
            --prompt "$prompt" \
            --timeout 120s
    else
        # Simulate agent response for demonstration
        simulate_agent_response
    fi
}

# Simulate agent response when kagent CLI is not available
simulate_agent_response() {
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${MAGENTA}  AGENT RESPONSE (Simulated)${NC}"
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Step 1: Knowledge retrieval
    print_agent "Querying internal knowledge base for 'CSI error 0x99'..."
    sleep 1
    echo ""
    echo -e "  ${GREEN}Found relevant documentation:${NC}"
    echo "  └── Storage-Failure-SOP-2025.pdf, Section 3.2"
    echo ""
    sleep 1

    # Step 2: Diagnosis
    print_agent "Analyzing the issue based on internal runbook..."
    sleep 1
    echo ""
    cat << 'EOF'
┌─────────────────────────────────────────────────────────────────┐
│                         DIAGNOSIS                               │
├─────────────────────────────────────────────────────────────────┤
│ Issue: CSI Error 0x99 - Stale Volume Attachment                 │
│                                                                 │
│ The NetApp-CSI driver has lost synchronization with the storage │
│ array. A VolumeAttachment resource exists for worker-node-03    │
│ but the actual attachment on the storage array was released.    │
└─────────────────────────────────────────────────────────────────┘
EOF
    echo ""
    sleep 1

    # Step 3: Citation
    print_agent "According to the Storage-Failure-SOP-2025, Section 3.2:"
    echo ""
    echo -e "  ${CYAN}\"If CSI error 0x99 occurs on NetApp-CSI, users must delete the${NC}"
    echo -e "  ${CYAN}stale 'volume-attachment' resource and apply the annotation${NC}"
    echo -e "  ${CYAN}'storage.internal/manual-unlock: true' to the PVC.\"${NC}"
    echo ""
    sleep 1

    # Step 4: Resolution
    print_agent "Executing resolution procedure from runbook..."
    echo ""

    echo -e "  ${YELLOW}Step 1:${NC} Deleting stale VolumeAttachment..."
    echo "  └── kubectl delete volumeattachment csi-abc123-worker-node-03"
    kubectl delete volumeattachment csi-abc123-worker-node-03 --ignore-not-found 2>/dev/null || true
    sleep 1
    echo -e "  ${GREEN}✓ Deleted${NC}"
    echo ""

    echo -e "  ${YELLOW}Step 2:${NC} Applying manual-unlock annotation to PVC..."
    echo "  └── kubectl annotate pvc database-storage-claim storage.internal/manual-unlock=true -n production-app"
    kubectl annotate pvc database-storage-claim storage.internal/manual-unlock=true -n production-app --overwrite 2>/dev/null || true
    sleep 1
    echo -e "  ${GREEN}✓ Annotation applied${NC}"
    echo ""

    # Step 5: Verification
    print_agent "Verifying the fix..."
    echo ""
    echo -e "  ${YELLOW}PVC Annotations:${NC}"
    kubectl get pvc database-storage-claim -n production-app -o jsonpath='{.metadata.annotations}' 2>/dev/null | tr ',' '\n' | sed 's/^/  /' || echo "  storage.internal/manual-unlock: true"
    echo ""
    echo ""

    # Final summary
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  RESOLUTION COMPLETE${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    cat << 'EOF'
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT SUMMARY                              │
├─────────────────────────────────────────────────────────────────┤
│ Source: Storage-Failure-SOP-2025.pdf, Section 3.2               │
│                                                                 │
│ Actions Taken:                                                  │
│ 1. ✓ Deleted stale VolumeAttachment: csi-abc123-worker-node-03  │
│ 2. ✓ Applied annotation: storage.internal/manual-unlock=true    │
│                                                                 │
│ Result: Pod should now be able to mount the volume.             │
│         The CSI driver will attempt re-attachment.              │
│                                                                 │
│ Note: This fix was found in INTERNAL documentation, not in      │
│       public Kubernetes docs. RAG retrieval was essential.      │
└─────────────────────────────────────────────────────────────────┘
EOF
    echo ""
}

# Show final status
show_results() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  DEMONSTRATION COMPLETE${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    echo -e "${GREEN}Key Takeaways:${NC}"
    echo ""
    echo "  1. ${BOLD}Knowledge-First Approach${NC}"
    echo "     The agent queried internal runbooks BEFORE attempting any fix."
    echo ""
    echo "  2. ${BOLD}Citation of Sources${NC}"
    echo "     The agent explicitly cited 'Storage-Failure-SOP-2025, Section 3.2'"
    echo "     providing audit trail and traceability."
    echo ""
    echo "  3. ${BOLD}Proprietary Fix Applied${NC}"
    echo "     The annotation 'storage.internal/manual-unlock: true' is specific"
    echo "     to our NetApp-CSI configuration - not found in public docs."
    echo ""
    echo "  4. ${BOLD}RAG Value Demonstrated${NC}"
    echo "     Without access to internal knowledge, a general LLM would suggest"
    echo "     generic troubleshooting that wouldn't resolve this specific issue."
    echo ""
}

# Cleanup function
cleanup() {
    print_info "Cleaning up resources..."

    kubectl delete -f "${SCRIPT_DIR}/failing-pvc.yaml" --ignore-not-found 2>/dev/null || true
    kubectl delete -f "${SCRIPT_DIR}/storage-sre-agent.yaml" --ignore-not-found 2>/dev/null || true
    kubectl delete -f "${SCRIPT_DIR}/storage-runbook-knowledge.yaml" --ignore-not-found 2>/dev/null || true
    kubectl delete namespace production-app --ignore-not-found 2>/dev/null || true

    print_status "Cleanup complete"
}

# Main execution
main() {
    case "${1:-run}" in
        run)
            print_header
            print_scenario
            check_prerequisites
            init_knowledge_base
            deploy_agent
            create_chaos
            echo ""
            read -p "Press Enter to invoke the Storage Expert Agent..." </dev/tty || true
            echo ""
            invoke_agent
            show_results
            ;;

        init)
            print_header
            check_prerequisites
            init_knowledge_base
            deploy_agent
            print_status "Initialization complete. Run './run-rag-test.sh chaos' to create the failure scenario."
            ;;

        chaos)
            create_chaos
            ;;

        invoke)
            invoke_agent
            ;;

        cleanup)
            cleanup
            ;;

        *)
            echo "Usage: $0 {run|init|chaos|invoke|cleanup}"
            echo ""
            echo "Commands:"
            echo "  run     - Run the complete demonstration"
            echo "  init    - Initialize knowledge base and deploy agent only"
            echo "  chaos   - Create the failing PVC scenario"
            echo "  invoke  - Invoke the agent to fix the issue"
            echo "  cleanup - Remove all deployed resources"
            exit 1
            ;;
    esac
}

main "$@"
