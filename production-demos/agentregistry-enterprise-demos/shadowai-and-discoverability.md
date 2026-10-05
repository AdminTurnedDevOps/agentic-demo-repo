## Showcasing ShadowAI For Managed And Unmanaged Instances

Within the UI, show:
1. Managed instances (the instances that are deployed by agentregistry)
2. Unmmanged instances (the instances that are discovered by agentregistry)


## Real-time Discoverability

### Agents

- Go into the Foundry Portal
- Go to **Build > Agents**
- Create a new Agent
- Wait about 30 seconds and you'll see the new Agent auto-discovered in agentregistry


### MCP

- Go to kagent
- Click on **Tool Servers**
- Add an MCP Server
- Go to agentregistry
- Click on **instances**
- Go to unmanaged instances
- click **Type > MCP Server**
- Wait about 30 seconds and you'll see the new MCP Server auto-discovered in agentregistry


## Virtual Runtime With Agentgateway

Show the virtual runtime, which is agentgateway, to explain that instead of agents connecting directly to MCP servers, the connection goes through the virtual runtime which provides security, observability, and governance of all MCP traffic.

- Gatway object: https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/assets/mcp/agentgateway/parent-gateway-and-route.yaml
- Runtime for the gateway/virtual runtime: https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/assets/mcp/agentgateway/virtual-default-runtime.yaml

## Adding Runtimes (AWS and Microsoft Foundry)

- Add runtimes in both the UI and arctl

Foundry runtime programmatically: https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/011-azure-ai-foundry-runtime.md
AgentCore runtime programmatically: https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/010-aws-bedrock-runtime.md

## Cataloging Of Agentic Resources

- Show how to see/create resources within the **Catalog** tab

## Access Policy

1. Open Access Policies in the dashboard
2. See the configuration that's available
3. Log out
4. Log in with `mlevan-svc`
5. Show whats available with the "read-only" user.

## Resource Deployment

Two methods:

1. Via the UI
2. With `arctl`

For example, with `arctl`, you can use the agentregistry API to add Prompts, Skills, etc. to the catalog (along with runtimes and any other object in agentregistry)

![example](https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/040-prompts.md)