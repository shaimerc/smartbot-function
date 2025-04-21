import azure.functions as func
from twilio.twiml.messaging_response import MessagingResponse
import requests
import openai
import os

# Secrets from environment or hardcoded for now (clean up later)
endpoint = os.getenv("CLU_ENDPOINT")
prediction_key = os.getenv("CLU_KEY")
project_name = os.getenv("CLU_PROJECT_NAME")
deployment_name = os.getenv("CLU_DEPLOYMENT_NAME")

openai_endpoint = os.getenv("OPENAI_ENDPOINT")
openai_key = os.getenv("OPENAI_KEY")
openai_deployment = os.getenv("OPENAI_DEPLOYMENT")

def get_intent(message: str):
    headers = {
        "Ocp-Apim-Subscription-Key": prediction_key,
        "Content-Type": "application/json"
    }

    body = {
        "kind": "Conversation",
        "analysisInput": {
            "conversationItem": {
                "participantId": "user1",
                "id": "1",
                "modality": "text",
                "language": "en",
                "text": message
            }
        },
        "parameters": {
            "projectName": project_name,
            "deploymentName": deployment_name,
            "verbose": True
        }
    }

    response = requests.post(
        f"{endpoint}/language/:analyze-conversations?api-version=2022-10-01-preview",
        headers=headers,
        json=body
    )
    result = response.json()
    intent = result["result"]["prediction"]["topIntent"]
    confidence = result["result"]["prediction"]["intents"][intent]["confidenceScore"]
    return intent, confidence

def generate_response_azure(user_input: str, detected_intent: str):
    openai.api_type = "azure"
    openai.api_base = openai_endpoint
    openai.api_version = "2024-03-01-preview"
    openai.api_key = openai_key

    response = openai.ChatCompletion.create(
        engine=openai_deployment,
        messages=[
            {"role": "system", "content": f"You are a smart support assistant. The user's intent is: {detected_intent}"},
            {"role": "user", "content": user_input}
        ],
        temperature=0.5,
        max_tokens=500
    )

    return response["choices"][0]["message"]["content"]
