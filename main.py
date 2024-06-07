import logging
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from core_functions import (
    add_thread, client, process_tool_calls, get_assistant_id, check_openai_version, 
    add_thread_to_sheet, load_tools_from_directory, open_spreadsheet_in_folder, 
    list_spreadsheets_in_folder
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# Check OpenAI version compatibility
check_openai_version()

# Create Flask app
app = Flask(__name__)
CORS(app)

# Initialize all available tools
tool_data = load_tools_from_directory('tools')

# Get assistant ID from environment variables
assistant_id = get_assistant_id()

# Initialize Flask-Limiter with explicit in-memory storage configuration
limiter = Limiter(key_func=get_remote_address,
                  storage_uri="memory://",
                  app=app,
                  default_limits=["200 per minute"])

# Get Google Drive folder ID and spreadsheet name from environment variables
drive_folder_id = os.getenv('DRIVE_FOLDER_ID')
sheet_name = os.getenv('SHEET_NAME')

# List spreadsheets in the specified folder
list_spreadsheets_in_folder(drive_folder_id)

# Open the specified spreadsheet in the specified folder
try:
    spreadsheet = open_spreadsheet_in_folder(drive_folder_id, sheet_name)
    sheet = spreadsheet.sheet1
except FileNotFoundError as e:
    logging.error(e)
    sheet = None  # Define `sheet` as None if the spreadsheet is not found

@app.route('/start', methods=['GET'])
@limiter.limit("50 per day")  # Limit to 50 conversations per day
def start_conversation():
    platform = request.args.get('platform', 'Not Specified')
    logging.info(f"Starting a new conversation from platform: {platform}")
    thread = client.beta.threads.create()
    logging.info(f"New thread created with ID: {thread.id}")

    if sheet is not None:
        add_thread_to_sheet(thread.id, platform, sheet)
    else:
        logging.error("Sheet not defined. Cannot add thread to sheet.")
        return jsonify({"error": "Sheet not defined"}), 500

    return jsonify({"thread_id": thread.id})

@app.route('/chat', methods=['POST'])
@limiter.limit("100 per day")  # Limit to 100 messages per day
def chat():
    data = request.json
    thread_id = data.get('thread_id')
    user_input = data.get('message', '')

    if not thread_id:
        logging.error("Error: Missing thread_id")
        return jsonify({"error": "Missing thread_id"}), 400

    logging.info(f"Received message: {user_input} for thread ID: {thread_id}")
    client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_input)
    run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)

    logging.info(f"Run ID: {run.id}")
    result = process_tool_calls(client, thread_id, run.id, tool_data)
    return jsonify(result)

@app.errorhandler(400)
def handle_400_error(e):
    logging.error(f"Bad Request: {e.description}")
    return jsonify(error="Bad Request", message=e.description), 400

@app.errorhandler(401)
def handle_401_error(e):
    logging.error(f"Unauthorized: {e.description}")
    return jsonify(error="Unauthorized", message=e.description), 401

@app.errorhandler(500)
def handle_500_error(e):
    logging.error(f"Internal Server Error: {e}")
    return jsonify(error="Internal Server Error", message="An unexpected error occurred"), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
