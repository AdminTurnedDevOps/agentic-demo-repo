az monitor metrics list --resource "/subscriptions/xxxx/resourceGroups/foundry/providers/Microsoft.CognitiveServices/accounts/mlevantesting01/projects/proj-default" --metric AgentResponses --aggregation Total --interval PT1M --filter "AgentId eq '*'"

  dependencies
  | where timestamp > ago(24h)
  | where tostring(customDimensions["microsoft.foundry"]) == "True"
  | extend
      agent_id = tostring(customDimensions["gen_ai.agent.id"]),
      response_id = tostring(customDimensions["gen_ai.response.id"]),
      conversation_id = tostring(customDimensions["gen_ai.conversation.id"]),
      operation = tostring(customDimensions["gen_ai.operation.name"]),
      input_tokens = toint(customDimensions["gen_ai.usage.input_tokens"]),
      output_tokens = toint(customDimensions["gen_ai.usage.output_tokens"])
  | project timestamp, name, operation_Id, operation_ParentId, agent_id, response_id, conversation_id, operation, input_tokens, output_tokens
  | order by timestamp desc

  For usage by agent:

  dependencies
  | where timestamp > ago(24h)
  | where tostring(customDimensions["microsoft.foundry"]) == "True"
  | where tostring(customDimensions["gen_ai.operation.name"]) == "chat"
  | extend
      agent_id = tostring(customDimensions["gen_ai.agent.id"]),
      response_id = tostring(customDimensions["gen_ai.response.id"]),
      model = tostring(customDimensions["gen_ai.response.model"]),
      input_tokens = toint(customDimensions["gen_ai.usage.input_tokens"]),
      output_tokens = toint(customDimensions["gen_ai.usage.output_tokens"]),
      cached_tokens = toint(customDimensions["gen_ai.usage.cached_tokens"])
  | summarize
      responses = dcount(response_id),
      input_tokens = sum(input_tokens),
      output_tokens = sum(output_tokens),
      cached_tokens = sum(cached_tokens),
      total_tokens = sum(input_tokens + output_tokens)
    by agent_id, model
  | order by total_tokens desc