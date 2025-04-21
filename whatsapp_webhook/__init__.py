import azure.functions as func

def main(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("Hello! Your message was received and processed.",
                             mimetype="text/plain")
