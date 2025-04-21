import azure.functions as func
from twilio.twiml.messaging_response import MessagingResponse
import requests
import openai
import os
import logging

logging.basicConfig(level=logging.INFO)

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

    try:
        result = response.json()
        logging.info(f"🧠 CLU raw result: {result}")

        prediction = result.get("result", {}).get("prediction", {})
        top_intent = prediction.get("topIntent", "unknown")
        intents = prediction.get("intents")

        # ✅ NEW: Handle both dict and list structures for intents
        confidence = 0.0
        if isinstance(intents, dict):
            confidence = intents.get(top_intent, {}).get("confidenceScore", 0.0)
        elif isinstance(intents, list):
            for intent_item in intents:
                if intent_item.get("category") == top_intent:
                    confidence = intent_item.get("confidenceScore", 0.0)
                    break

        return top_intent, confidence

    except Exception as e:
        logging.error(f"❌ Error parsing CLU response: {str(e)}")
        raise

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
        logging.info("📩 Function triggered by HTTP request.")

        # Pull user message
        user_message = req.form.get('Body') or req.params.get('Body')
        sender = req.form.get('From')

        logging.info(f"📨 Received message from {sender}: {user_message}")

        # Confirm environment variables are loaded
        if not all([endpoint, prediction_key, project_name, deployment_name,
                    openai.api_base, openai.api_key, openai_deployment]):
            logging.error("🚨 One or more environment variables are missing!")
            return func.HttpResponse("Server error: Missing environment variables.", status_code=500)

        # Try calling CLU
        try:
            intent, confidence = get_intent(user_message)
            logging.info(f"🎯 Detected intent: {intent} (confidence: {confidence:.2f})")
        except Exception as clu_err:
            logging.error(f"❌ Error calling CLU: {clu_err}")
            return func.HttpResponse(f"CLU Error: {str(clu_err)}", status_code=500)

        # Try generating response
        try:
            reply = generate_response_azure(user_message, intent)
            logging.info(f"💬 GPT reply: {reply}")
        except Exception as openai_err:
            logging.error(f"❌ Error calling OpenAI: {openai_err}")
            reply = "Sorry, I couldn't generate a response."

        # Final fallback
        if not reply:
            reply = "Sorry, no response could be generated."

        # Build Twilio-compatible reply
        twilio_response = MessagingResponse()
        twilio_response.message(reply)
        logging.info(f"✅ Final XML: {str(twilio_response)}")

        return func.HttpResponse(str(twilio_response), mimetype="application/xml")

    except Exception as e:
        logging.error(f"❌ Unhandled exception: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)

        # return func.HttpResponse(str(twilio_response), mimetype="application/xml")

    except Exception as e:
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
