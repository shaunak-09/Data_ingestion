"""Azure Functions (Python v2) entry point. Registers the function blueprints."""

import azure.functions as func

from triggers.api import bp as api_blueprint
from triggers.csv import bp as csv_blueprint
from triggers.upload import bp as upload_blueprint

app = func.FunctionApp()
app.register_functions(csv_blueprint)
app.register_functions(api_blueprint)
app.register_functions(upload_blueprint)
