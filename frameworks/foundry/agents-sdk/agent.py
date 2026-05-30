from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

def main():
    
    client = AIProjectClient(
        endpoint = "https://mlevanproj-resource.services.ai.azure.com/api/projects/mlevanproj",
        credential = DefaultAzureCredential()
    )
    
    with client.get_openai_client() as openai_client:
        response = openai_client.responses.create(
            model="gpt-4.1-mini",
            input="What is an Agent Harness?",
            max_output_tokens=200,
            temperature=0.2,
            tools=[{
                "type": "web_search"
            }]
        )
        print(f"Response output: {response.output_text}")
    
main()