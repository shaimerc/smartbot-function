import azure.functions as func
from twilio.twiml.messaging_response import MessagingResponse
import requests
import openai
import os
import logging

from openai import AzureOpenAI

logging.basicConfig(level=logging.INFO)

# Required credentials (stored as App Settings in Azure)
endpoint = os.getenv("CLU_ENDPOINT")
prediction_key = os.getenv("CLU_KEY")
project_name = os.getenv("CLU_PROJECT_NAME")
deployment_name = os.getenv("CLU_DEPLOYMENT_NAME")



openai.api_type = "azure"
openai.api_base = os.getenv("OPENAI_ENDPOINT")
openai.api_version = "2024-12-01-preview"
openai.api_key = os.getenv("OPENAI_KEY")
openai_deployment = os.getenv("OPENAI_DEPLOYMENT")  # e.g., sjm-sig788-t8hd-gpt-4o

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

def transcribe_audio_file(audio_path: str) -> str:
    try:
        speech_key = os.getenv("SPEECH_KEY_T8HD")
        speech_region = os.getenv("SPEECH_REGION_T8HD")

        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        audio_config = speechsdk.audio.AudioConfig(filename=audio_path)
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

        logging.info(f"🔊 Transcribing audio file: {audio_path}")
        result = recognizer.recognize_once()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            logging.info(f"✅ Recognized speech: {result.text}")
            return result.text
        else:
            logging.warning(f"⚠️ Speech recognition failed. Reason: {result.reason}")
            return None

    except Exception as e:
        logging.error(f"❌ Exception in transcribe_audio_file: {str(e)}", exc_info=True)
        return None

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
            logging.error(f"❌ OCR submission failed: {response.status_code}, {response.text}")
            return None

        result_url = response.headers["Operation-Location"]
        time.sleep(2)

        for _ in range(10):
            result = requests.get(result_url, headers={"Ocp-Apim-Subscription-Key": cv_key})
            result_json = result.json()
            status = result_json.get("status", "")

            if status == "succeeded":
                lines = []
                for read_result in result_json["analyzeResult"]["readResults"]:
                    for line in read_result["lines"]:
                        lines.append(line["text"])
                extracted_text = "\n".join(lines)
                logging.info(f"✅ OCR extracted text: {extracted_text}")
                return extracted_text

            elif status == "failed":
                logging.warning("⚠️ OCR request failed.")
                return None

            time.sleep(1)

        logging.error("❌ OCR request timed out.")
        return None

    except Exception as e:
        logging.error(f"❌ Exception in extract_text_from_image: {str(e)}", exc_info=True)
        return None


client = AzureOpenAI(
    api_key=openai.api_key,
    api_version=openai.api_version,
    azure_endpoint=openai.api_base,
)

def generate_response_azure(user_input: str, detected_intent: str):
    try:
        response = client.chat.completions.create(
            model=openai_deployment,
            messages=[
                {"role": "system", "content": f"You are a smart customer assistant. The user's intent is: {detected_intent}"},
                {"role": "user", "content": user_input}
            ],
            temperature=0.5,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"❌ OpenAI Chat API error: {e}")
        return "Sorry, I couldn't generate a response."



# ✅ This is the required main function Azure looks for
def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("📩 Function triggered by HTTP request.")

    # WhatsApp message basics
    sender = req.form.get('From')
    user_message = req.form.get('Body') or req.params.get('Body')
    num_media = int(req.form.get("NumMedia", 0))

    # Log media presence
    logging.info(f"📨 Message from {sender}. Media Count: {num_media}")

    # Handle media input (image or voice)
    if num_media > 0:
        media_url = req.form.get("MediaUrl0")
        media_type = req.form.get("MediaContentType0")
        logging.info(f"📷 Media received: {media_type} at {media_url}")

        # Download media file
        try:
            response = requests.get(media_url)
            extension = media_type.split("/")[-1].split(";")[0]
            local_file_path = f"/tmp/media_input.{extension}"
            with open(local_file_path, "wb") as f:
                f.write(response.content)
        except Exception as media_err:
            logging.error(f"❌ Failed to download media file: {media_err}")
            return func.HttpResponse("Failed to process uploaded media.", status_code=500)

        # Route based on type
        if "audio" in media_type:
            user_message = transcribe_audio_file(local_file_path)
            logging.info(f"🗣️ Transcribed voice: {user_message}")
        elif "image" in media_type:
            user_message = extract_text_from_image(local_file_path)
            logging.info(f"🖼️ Extracted text: {user_message}")

    if not user_message:
        return func.HttpResponse("No usable message found.", status_code=200)

    # CLU intent recognition
    intent, confidence = get_intent(user_message)
    logging.info(f"🎯 Intent: {intent} (confidence: {confidence:.2f})")

    # Generate GPT response
    try:
        reply = generate_response_azure(user_message, intent)
        logging.info(f"💬 GPT reply: {reply}")
    except Exception as openai_err:
        logging.error(f"❌ Error calling OpenAI: {openai_err}", exc_info=True)
        reply = "Sorry, I couldn't generate a response, OpenAI Issue."

    if not reply:
        reply = "Sorry, no response could be generated."

    # Send reply to WhatsApp
    twilio_response = MessagingResponse()
    twilio_response.message(reply)

    return func.HttpResponse(str(twilio_response), mimetype="application/xml")
