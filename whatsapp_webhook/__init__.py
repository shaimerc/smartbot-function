import azure.functions as func
from twilio.twiml.messaging_response import MessagingResponse
import openai
from openai import AzureOpenAI, OpenAI
import requests
import os
import logging
import mimetypes
import uuid
import time

# Configure minimal logging
logging.basicConfig(level=logging.INFO)

# Load environment variables for CLU and Azure OpenAI
endpoint = os.getenv("CLU_ENDPOINT")
prediction_key = os.getenv("CLU_KEY")
project_name = os.getenv("CLU_PROJECT_NAME")
deployment_name = os.getenv("CLU_DEPLOYMENT_NAME")

# Azure OpenAI deployment config
openai.api_type = "azure"
openai.api_base = os.getenv("OPENAI_ENDPOINT")
openai.api_version = "2024-12-01-preview"
openai.api_key = os.getenv("OPENAI_KEY")
openai_deployment = os.getenv("OPENAI_DEPLOYMENT")

# Initialize Azure OpenAI client globally
client = AzureOpenAI(
    api_key=openai.api_key,
    api_version=openai.api_version,
    azure_endpoint=openai.api_base,
)

# --- Function: Detect user's intent using Azure CLU ---
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

    prediction = response.json().get("result", {}).get("prediction", {})
    top_intent = prediction.get("topIntent", "unknown")
    intents = prediction.get("intents", {})

    # Support both dict and list formats
    confidence = 0.0
    if isinstance(intents, dict):
        confidence = intents.get(top_intent, {}).get("confidenceScore", 0.0)
    elif isinstance(intents, list):
        for intent_item in intents:
            if intent_item.get("category") == top_intent:
                confidence = intent_item.get("confidenceScore", 0.0)
                break

    return top_intent, confidence

# --- Function: Download media file from Twilio ---
def download_media(media_url: str, filename="media_file") -> str:
    try:
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        response = requests.get(media_url, auth=(account_sid, auth_token))

        if response.status_code != 200:
            return None

        extension = mimetypes.guess_extension(response.headers.get("Content-Type", "application/octet-stream")) or ".bin"
        local_path = f"/tmp/{filename}_{uuid.uuid4().hex}{extension}"

        with open(local_path, "wb") as f:
            f.write(response.content)

        return local_path

    except Exception as e:
        logging.error(f"Error downloading media: {e}", exc_info=True)
        return None

# --- Function: Transcribe audio file using Whisper (OpenAI Public API) ---
def transcribe_audio_file(audio_path: str) -> str:
    try:
        whisper_key = os.getenv("OPENAI_PUBLIC_KEY")
        if not whisper_key:
            return None

        whisper_client = OpenAI(api_key=whisper_key)

        with open(audio_path, "rb") as audio_file:
            response = whisper_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )

        return response.text.strip() if response.text else None

    except Exception as e:
        logging.error(f"Whisper transcription failed: {e}", exc_info=True)
        return None

# --- Function: Extract text from image using Azure Computer Vision OCR ---
def extract_text_from_image(image_path: str) -> str:
    try:
        cv_endpoint = os.getenv("CV_ENDPOINT_T8HD")
        cv_key = os.getenv("CV_KEY_T8HD")

        ocr_url = f"{cv_endpoint}/vision/v3.2/read/analyze"
        headers = {
            "Ocp-Apim-Subscription-Key": cv_key,
            "Content-Type": "application/octet-stream"
        }

        with open(image_path, "rb") as f:
            image_data = f.read()

        response = requests.post(ocr_url, headers=headers, data=image_data)
        if response.status_code != 202:
            return None

        result_url = response.headers["Operation-Location"]
        time.sleep(2)

        for _ in range(10):
            result = requests.get(result_url, headers=headers).json()
            if result.get("status") == "succeeded":
                lines = [line["text"] for read in result["analyzeResult"]["readResults"] for line in read["lines"]]
                return "\n".join(lines).strip()
            elif result.get("status") == "failed":
                return None
            time.sleep(1)

        return None

    except Exception as e:
        logging.error(f"OCR error: {e}", exc_info=True)
        return None

# --- Function: Generate response from Azure GPT (GPT-4o) ---
def generate_response_azure(user_input: str, detected_intent: str):
    try:
        response = client.chat.completions.create(
            model=openai_deployment,
            messages=[
                {"role": "system", "content": f"You are a smart assistant. Limit response to 1500 characters. Intent: {detected_intent}"},
                {"role": "user", "content": user_input}
            ],
            temperature=0.5,
            max_tokens=350
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"OpenAI Chat error: {e}")
        return "Sorry, I couldn't generate a response."

# --- Azure Function entry point ---
def main(req: func.HttpRequest) -> func.HttpResponse:
    sender = req.form.get("From")
    user_message = req.form.get("Body") or req.params.get("Body")
    num_media = int(req.form.get("NumMedia", 0))

    # Process media input (audio/image)
    if num_media > 0:
        media_url = req.form.get("MediaUrl0")
        media_type = req.form.get("MediaContentType0")

        file_path = download_media(media_url)
        if not file_path:
            return func.HttpResponse("Media download failed.", status_code=500)

        if "audio" in media_type:
            user_message = transcribe_audio_file(file_path)
        elif "image" in media_type:
            user_message = extract_text_from_image(file_path)

    if not user_message:
        return func.HttpResponse("No usable message found.", status_code=200)

    # Process intent and generate response
    intent, _ = get_intent(user_message)
    reply = generate_response_azure(user_message, intent) or "Sorry, no response could be generated."

    # Send reply to WhatsApp
    twilio_response = MessagingResponse()
    twilio_response.message(reply)
    return func.HttpResponse(str(twilio_response), mimetype="application/xml")
