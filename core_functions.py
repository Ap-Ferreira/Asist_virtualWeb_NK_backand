import importlib.util
import logging
import openai
import os
import requests
import json
import re
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from googleapiclient.discovery import build
from flask import request, abort, jsonify
from packaging import version

# Cargar las variables de entorno desde el entorno
AIRTABLE_DB_URL = os.getenv('AIRTABLE_DB_URL')
AIRTABLE_API_KEY = f"Bearer {os.getenv('AIRTABLE_API_KEY')}"
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ASSISTANT_ID = os.getenv('ASSISTANT_ID')
CUSTOM_API_KEY = os.getenv('CUSTOM_API_KEY')
GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv('SHEETS_CREDENTIALS')
GOOGLE_DRIVE_FOLDER_PATH = os.getenv('DRIVE_FOLDER_PATH')
SHEET_NAME = os.getenv('SHEET_NAME')

# Initialize OpenAI client with v2 API header
if not OPENAI_API_KEY:
    raise ValueError("No OpenAI API key found in environment variables")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Configuración de las credenciales y alcance de Google Sheets y Drive
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_PATH,
                                              scopes=scope)
sheets_client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)


def get_or_create_folder(folder_name):
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    results = drive_service.files().list(q=query, spaces='drive').execute()
    items = results.get('files', [])

    if not items:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = drive_service.files().create(body=file_metadata,
                                              fields='id').execute()
        folder_id = folder.get('id')
        logging.info(f"Folder '{folder_name}' created with ID: {folder_id}")
    else:
        folder_id = items[0]['id']
        logging.info(
            f"Folder '{folder_name}' already exists with ID: {folder_id}")

    return folder_id


def list_spreadsheets_in_folder(folder_id):
    query = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    results = drive_service.files().list(q=query, spaces='drive').execute()
    items = results.get('files', [])

    if not items:
        logging.info('No spreadsheets found in folder.')
    else:
        logging.info('Spreadsheets found in folder:')
        for item in items:
            logging.info(f"{item['name']} (ID: {item['id']})")


def debug_list_files_in_folder(folder_id):
    query = f"'{folder_id}' in parents and trashed=false"
    results = drive_service.files().list(q=query, spaces='drive').execute()
    items = results.get('files', [])

    if not items:
        logging.info('No files found in folder.')
    else:
        logging.info('Files found in folder:')
        for item in items:
            logging.info(
                f"Name: {item['name']}, MIME type: {item['mimeType']}, ID: {item['id']}"
            )


def open_spreadsheet_in_folder(folder_id, spreadsheet_name):
    query = f"'{folder_id}' in parents and name='{spreadsheet_name}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    results = drive_service.files().list(q=query, spaces='drive').execute()
    items = results.get('files', [])

    if not items:
        raise FileNotFoundError(
            f"Spreadsheet '{spreadsheet_name}' not found in folder '{folder_id}'"
        )

    spreadsheet_id = items[0]['id']
    return sheets_client.open_by_key(spreadsheet_id)


def add_thread_to_sheet(thread_id, platform, sheet):
    try:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sheet.append_row([thread_id, platform, '', current_time])
        num_rows = len(sheet.get_all_values())
        sheet.update_cell(num_rows, 5, "Arrived")
        logging.info("Thread added to sheet successfully and 'Arrived' set.")
    except Exception as e:
        logging.error(f"An error occurred while adding the thread to the sheet: {e}")



def check_openai_version():
    required_version = version.parse("1.1.1")
    current_version = version.parse(openai.__version__)
    if current_version < required_version:
        raise ValueError(
            f"Error: OpenAI version {openai.__version__} is less than the required version 1.1.1"
        )
    else:
        logging.info("OpenAI version is compatible.")


def check_api_key():
    api_key = request.headers.get('X-API-KEY')
    if api_key != CUSTOM_API_KEY:
        logging.info(f"Invalid API key: {api_key}")
        abort(401)


def add_thread(thread_id, platform):
    url = f"{AIRTABLE_DB_URL}"
    headers = {
        "Authorization": f"{AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "records": [{
            "fields": {
                "Thread_id": thread_id,
                "Platform": platform
            }
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            logging.info("Thread added to DB successfully.")
        else:
            logging.error(
                f"Failed to add thread: HTTP Status Code {response.status_code}, Response: {response.text}"
            )
    except Exception as e:
        logging.error(f"An error occurred while adding the thread: {e}")


def process_tool_calls(client, thread_id, run_id, tool_data):
    while True:
        run_status = client.beta.threads.runs.retrieve(thread_id=thread_id,
                                                       run_id=run_id)
        logging.info(f" -> Checking run status: {run_status.status}")
        if run_status.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id)
            message_content = messages.data[0].content[0].text.value
            logging.info(f"Message content before cleaning: {message_content}")

            message_content = re.sub(r"【.*?†.*?】", '', message_content)
            message_content = re.sub(r'[^\S\r\n]+', ' ',
                                     message_content).strip()

            return {"response": message_content, "status": "completed"}
        elif run_status.status == 'requires_action':
            for tool_call in run_status.required_action.submit_tool_outputs.tool_calls:
                function_name = tool_call.function.name

                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    logging.error(
                        f"JSON decoding failed: {e.msg}. Input: {tool_call.function.arguments}"
                    )
                    arguments = {}

                if function_name in tool_data["function_map"]:
                    function_to_call = tool_data["function_map"][function_name]
                    output = function_to_call(arguments)
                    client.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run_id,
                        tool_outputs=[{
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(output)
                        }])
                else:
                    logging.warning(
                        f"Function {function_name} not found in tool data.")

        elif run_status.status == 'failed':
            return jsonify({"response": "error", "status": "failed"})

        time.sleep(4)


def load_tools_from_directory(directory):
    tool_data = {"tool_configs": [], "function_map": {}}

    for filename in os.listdir(directory):
        if filename.endswith('.py'):
            module_name = filename[:-3]
            module_path = os.path.join(directory, filename)
            spec = importlib.util.spec_from_file_location(
                module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, 'tool_config'):
                tool_data["tool_configs"].append(module.tool_config)

            for attr in dir(module):
                attribute = getattr(module, attr)
                if callable(attribute) and not attr.startswith("__"):
                    tool_data["function_map"][attr] = attribute

    return tool_data


def get_assistant_id():
    assistant_id = os.getenv('ASSISTANT_ID')
    if not assistant_id:
        raise ValueError(
            "Assistant ID not found in environment variables. Please set ASSISTANT_ID."
        )
    logging.info("Loaded existing assistant ID from environment variable.")
    return assistant_id
