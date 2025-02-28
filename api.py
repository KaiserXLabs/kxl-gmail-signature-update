import io
import json
import logging
import requests
from typing import Optional, Dict, Any, List
from google.auth.credentials import Credentials
from google.oauth2 import service_account
from google.cloud import secretmanager
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_credentials(user_email: str, scopes: List[str], project_id: str, secret_name: str) -> service_account.Credentials:
    """
    Retrieves OAuth2 credentials for a given user email and scopes using a service account key stored in Google Secret Manager.

    Args:
        user_email (str): The email address of the user for whom the credentials are being requested.
        scopes (List[str]): A list of OAuth2 scopes that the credentials should have access to.
        project_id (str): The Google Cloud project ID.
        secret_name (str): The name of the secret in Secret Manager.

    Returns:
        google.oauth2.service_account.Credentials: The OAuth2 credentials for the specified user and scopes.

    Raises:
        Exception: If there is an error accessing the secret or loading the credentials.
    """
    try:
        # Initialize the Secret Manager client
        client = secretmanager.SecretManagerServiceClient()

        # Build the resource name of the secret version
        secret_version_name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"

        # Access the secret
        response = client.access_secret_version(name=secret_version_name)
        secret_payload = response.payload.data.decode("UTF-8")  # Decode the secret data

        # Parse the JSON service account key
        service_account_info = json.loads(secret_payload)

        # Load credentials from the service account key
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=scopes,
            subject=user_email,
        )

        credentials.refresh(Request())
        return credentials

    except Exception as e:
        logger.error(f"Error retrieving credentials for user {user_email}: {str(e)}")
        raise


def check_if_file_exists_in_drive(file_name: str, drive_id: str, folder_id: str, 
                                  credentials: service_account.Credentials) -> Optional[str]:
    """
    Check if a file exists in Google Drive
    
    Args:
        file_name (str): The name of the file
        drive_id (str): The id of the drive
        folder_id (str): The id of the folder
        credentials (google.oauth2.service_account.Credentials): The credentials to use

    Returns:
        Optional[str]: The id of the file if it exists, None otherwise

    Raises:
        HttpError: If there is an error accessing the Google Drive API
        Exception: If duplicate files are found
    """
    try:
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)

        query = f"name='{file_name}' and trashed=false and mimeType='text/html' and '{folder_id}' in parents"
        results = service.files().list(
            q=query,
            driveId=drive_id,
            corpora="drive",
            spaces="drive",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        files = results.get("files", [])

        if not files:
            return None
        elif len(files) == 1:
            file_id = files[0].get("id")
            return file_id
        else:
            logger.error(f"Found multiple files with name: {file_name}")
            raise Exception("There are duplicate files existing already")

    except HttpError as e:
        logger.error(f"Google Drive API error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error checking if file exists: {str(e)}")
        raise


def create_file_in_drive(file_name: str,
                         drive_id: str,
                         folder_id: str,
                         signature: str,
                         credentials: Credentials) -> Optional[str]:
    """
    Create a file in Google Drive

    Args:
        file_name (str): The name of the file
        drive_id (str): The id of the drive
        folder_id (str): The id of the folder
        signature (str): The signature to upload
        credentials (google.auth.credentials.Credentials): The credentials to use

    Returns:
        Optional[str]: The id of the created file or None if creation failed

    Raises:
        HttpError: If there is an error with the Google Drive API
    """
    try:
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        file_metadata = {
            "name": file_name,
            "mimeType": "text/html",
            "parents": [folder_id],
            "driveId": drive_id,
        }
        media = MediaIoBaseUpload(
            io.BytesIO(signature.encode("utf-8")),
            mimetype="text/html",
        )

        file = service.files().create(
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True,
            fields="id",
        ).execute()

        file_id = file.get("id")
        return file_id
    except HttpError as e:
        logger.error(f"Google Drive API error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error creating file in Drive: {str(e)}")
        return None


def update_file_in_drive(file_id: str, signature: str, credentials: service_account.Credentials) -> None:
    """
    Update a file in Google Drive

    Args:
        file_id (str): The id of the file
        signature (str): The signature to upload
        credentials (google.oauth2.service_account.Credentials): The credentials to use

    Raises:
        HttpError: If there is an error with the Google Drive API
    """
    try:
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        media_body = MediaIoBaseUpload(
            io.BytesIO(signature.encode("utf-8")),
            mimetype="text/html",
        )

        service.files().update(
            fileId=file_id,
            media_body=media_body,
            supportsAllDrives=True,
        ).execute()
    except HttpError as e:
        logger.error(f"Google Drive API error when updating file {file_id}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error updating file in Drive: {str(e)}")
        raise


def get_text_from_doc(doc_id: str, token: str) -> str:
    """
    Get the text content of a Google Doc

    Args:
        doc_id (str): The id of the Google Doc
        token (str): The token to use

    Returns:
        str: The text content of the Google Doc

    Raises:
        requests.exceptions.RequestException: If there is an error with the HTTP request
    """
    try:
        url = f"https://docs.google.com/feeds/download/documents/export/Export?id={doc_id}&exportFormat=txt"
        headers = {
            'Authorization': f'Bearer {token}'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        logger.error(f"Error retrieving document content for doc id {doc_id}: {str(e)}")
        raise


def update_gmail_signature(employee_id: str, signature: str, token: str) -> Dict[str, Any]:
    """
    Update the Gmail signature of an employee
    
    Args:
        employee_id (str): The email of the employee
        signature (str): The signature to update
        token (str): The token to use
        
    Returns:
        Dict[str, Any]: The response from the API
    
    Raises:
        requests.exceptions.RequestException: If there is an error with the HTTP request
    """
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/{employee_id}/settings/sendAs/{employee_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        data = {
            "sendAsEmail": employee_id,
            "displayName": "",
            "replyToAddress": "",
            "signature": signature,
            "isPrimary": True,
            "isDefault": True,
        }

        response = requests.put(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error updating Gmail signature for employee {employee_id}: {str(e)}")
        raise


def get_all_employees(credentials: service_account.Credentials) -> List[Dict[str, Any]]:
    """
    Get all employees from the Google Admin Directory
    
    Args:
        credentials (google.oauth2.service_account.Credentials): The credentials to use
        
    Returns:
        List[Dict[str, Any]]: The list of employees
        
    Raises:
        HttpError: If there is an error with the Google Directory API
    """
    try:
        # Create a service object for the Admin Directory API
        service = build("admin", "directory_v1", credentials=credentials, cache_discovery=False)

        # Fields to retrieve from the Directory API
        required_fields = [
            "nextPageToken",
            "users/primaryEmail",
            "users/suspended",
            "users/archived",
            "users/orgUnitPath",
            "users/name/givenName",
            "users/name/familyName",
            "users/phones",
            "users/addresses",
            "users/organizations",
            "users/customSchemas/Personal_Information/Pronouns",
            "users/customSchemas/Personal_Information/GernePerDu",
            "users/customSchemas/Contractual_Information/Management_Role"
        ]

        # Initialize result list and page token
        result = []
        page_token = None

        # Loop through pages of users
        while True:
            response = service.users().list(
                domain="kaiser-x.com",
                fields=",".join(required_fields),
                pageToken=page_token,
                projection="full",
                maxResults=100,
                orderBy="email",
                sortOrder="ASCENDING",
            ).execute()

            users = response.get("users", [])
            result.extend(users)

            # Get the next page token
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return result
    except HttpError as e:
        logger.error(f"Google Directory API error: {str(e)}")
        raise
