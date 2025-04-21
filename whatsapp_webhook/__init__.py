import azure.functions as func
from twilio.twiml.messaging_response import MessagingResponse
from your_pipeline import get_intent, generate_response_azure  # Replace with actual code

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        user_message = req.form.get('Body')
        sender = req.form.get('From')

        intent, _ = get_intent(user_message)
        reply = generate_response_azure(user_message, intent)

        twilio_response = MessagingResponse()
        twilio_response.message(reply)

        return func.HttpResponse(str(twilio_response), mimetype="application/xml")
    except Exception as e:
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)