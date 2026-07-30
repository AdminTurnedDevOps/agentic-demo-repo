from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

def main():
    
    client = AIProjectClient(
        endpoint = "https://mlevanproj-resource.services.ai.azure.com/api/projects/mlevanproj",
        credential = DefaultAzureCredential()
    )
    
    with client.get_openai_client() as openai_client:
        response = openai_client.responses.create(
            model="qwen3-32b",
            input="Do you need to understand Machine Learning to learn Deep Learning?",
            max_output_tokens=200,
            temperature=0.1,
        )
        print(f"Response output: {response.output_text}")
    
main()