import azure.functions as func
import logging

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Function triggered.")

    try:
        return func.HttpResponse("Function executed successfully.", status_code=200)
    except Exception as e:
        logging.error(f"Exception: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
