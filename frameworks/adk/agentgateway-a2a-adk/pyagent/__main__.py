import click
import uvicorn
import logging
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import InMemoryCredentialService
from .agent import root_agent

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@click.command()
@click.option('--host', default='localhost', help='Host to bind the server to')
@click.option('--port', default=9999, type=int, help='Port to bind the server to')
def main(host: str, port: int):
    """Run the K8s Assistant A2A agent."""

    # Define agent capabilities
    capabilities = AgentCapabilities(
        streaming=True,
    )

    # Define agent skill
    skill = AgentSkill(
        id='kubernetes_assistant',
        name='Kubernetes Assistant',
        description='Expert assistant for Kubernetes and Istio Service Mesh questions with live cluster access',
        tags=['kubernetes', 'istio', 'k8s', 'cluster', 'pods'],
        examples=[
            'List all pods in the cluster',
            'Show me the logs from a specific pod',
            'What namespaces are available?',
            'Check recent cluster events',
            'How do I create a deployment in Kubernetes?',
            'Explain Istio traffic management',
        ],
    )

    # Create agent card
    agent_card = AgentCard(
        name='K8s Assistant',
        description='You are a Kubernetes expert. Answer questions about all things Kubernetes and Istio Service Mesh to the best of your ability',
        url=f'http://{host}:{port}/',
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=capabilities,
        skills=[skill],
    )

    # Create runner factory
    async def create_runner() -> Runner:
        try:
            logger.info("Creating Runner instance...")
            runner = Runner(
                app_name='k8sassistant',
                agent=root_agent,
                artifact_service=InMemoryArtifactService(),
                session_service=InMemorySessionService(),
                memory_service=InMemoryMemoryService(),
                credential_service=InMemoryCredentialService(),
            )
            logger.info("Runner instance created successfully")
            return runner
        except Exception as e:
            logger.error(f"Error creating Runner: {e}", exc_info=True)
            raise

    # Create agent executor
    agent_executor = A2aAgentExecutor(runner=create_runner)

    # Create request handler
    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=InMemoryTaskStore(),
    )

    # Create A2A application
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler
    )

    # Run the server (CORS is handled by agentgateway config.yaml)
    logger.info(f"Starting K8s Assistant A2A agent on {host}:{port}")
    print(f"Starting K8s Assistant A2A agent on {host}:{port}")

    try:
        uvicorn.run(
            server.build(),
            host=host,
            port=port,
            log_level="debug"
        )
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()
