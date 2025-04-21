import azure.functions as func
from twilio.twiml.messaging_response import MessagingResponse
import requests
import openai
import os
import logging

# Required credentials (stored as App Settings in Azure)
endpoint = os.getenv("CLU_ENDPOINT")
prediction_key = os.getenv("CLU_KEY")
project_name = os.getenv("CLU_PROJECT_NAME")
deployment_name = os.getenv("CLU_DEPLOYMENT_NAME")

openai.api_type = "azure"
openai.api_base = os.getenv("OPENAI_ENDPOINT")
openai.api_version = "2024-03-01-preview"
openai.api_key = os.getenv("OPENAI_KEY")
openai_deployment = os.getenv("OPENAI_DEPLOYMENT")  # e.g., sjm-sig788-t8hd-gpt-4o

logging.info(f"🔧 CLU_ENDPOINT = {endpoint}")
logging.info(f"🔧 CLU_KEY = {prediction_key}")
logging.info(f"🔧 CLU_PROJECT_NAME = {project_name}")
logging.info(f"🔧 CLU_DEPLOYMENT_NAME = {deployment_name}")
logging.info(f"🔧 OPENAI_ENDPOINT = {openai.api_base}")
logging.info(f"🔧 OPENAI_KEY = {openai.api_key}")
logging.info(f"🔧 OPENAI_DEPLOYMENT = {openai_deployment}")

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
    response = openai.ChatCompletion.create(
        engine=openai_deployment,
        messages=[
            {"role": "system", "content": f"You are a smart customer assistant. The user's intent is: {detected_intent}"},
            {"role": "user", "content": user_input}
        ],
        temperature=0.5,
        max_tokens=500
    )

    return response["choices"][0]["message"]["content"]

# ✅ This is the required main function Azure looks for
def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        user_message = req.form.get('Body')
        sender = req.form.get('From')

        intent, _ = get_intent(user_message)
        reply = generate_response_azure(user_message, intent)

        if not reply:
            reply = "Sorry, I couldn’t generate a response at the moment."

        twilio_response = MessagingResponse()
        twilio_response.message(reply)

        logging.info(f"🟢 Twilio XML: {str(twilio_response)}")

        return func.HttpResponse(reply, mimetype="text/plain")

        # return func.HttpResponse(str(twilio_response), mimetype="application/xml")

    except Exception as e:
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
