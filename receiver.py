import os
import api
import json
import base64
import logging
import uvicorn
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from google.oauth2 import service_account


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


SHARED_DRIVE_ID = os.getenv("SHARED_DRIVE_ID", "0AO-LUW_4xJ9mUk9PVA")
SHARED_DRIVE_FOLDER_ID = os.getenv("SHARED_DRIVE_FOLDER_ID", "1frS-KLEc5B30g8DCewfvnbiAfUDSZoDf")
PROJECT_ID = os.getenv("PROJECT_ID", "gsuite-tools-311209")
SECRET_NAME = os.getenv("SECRET_NAME", "pushSignatures_GSUITE_ACCESS_KEYFILE")
PORT = int(os.getenv("PORT", "8080"))


# Scopes required for modifying Gmail settings and writing to Drive
SCOPES_PERSONAL = [
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/drive.file",
]


# Pydantic models for request/response validation
class PubSubMessageData(BaseModel):
    """Model for the data field in a Pub/Sub message."""
    data: str = Field(..., description="Base64-encoded message data")
    message_id: Optional[str] = Field(None, description="Message ID")
    publish_time: Optional[str] = Field(None, description="Publish time")


class PubSubMessage(BaseModel):
    """Model for Pub/Sub message structure."""
    message: PubSubMessageData = Field(..., description="The Pub/Sub message")
    subscription: str = Field(..., description="The Pub/Sub subscription")


class SignatureMessage(BaseModel):
    """Model for the decoded signature message."""
    employee_id: str = Field(..., description="Employee ID (email)")
    signature: str = Field(..., description="HTML signature content")


class SignatureResponse(BaseModel):
    """Model for the API response."""
    status: str = Field(..., description="Status message")
    employee_id: str = Field(..., description="Employee ID that was processed")


# Initialize FastAPI app
app = FastAPI(
    title="Gmail Signature Receiver",
    description="Service for receiving and applying Gmail signature updates",
    version="1.0.0"
)


def write_signature_to_drive(
    employee_id: str, 
    signature: str, 
    credentials: service_account.Credentials
) -> Optional[str]:
    """
    Writes an employee's email signature to Google Drive.
    
    If a file with the employee's ID already exists, it updates the file.
    Otherwise, it creates a new file.

    Args:
        employee_id (str): The ID (email) of the employee.
        signature (str): The HTML content of the email signature.
        credentials (service_account.Credentials): The credentials for Google Drive API.

    Returns:
        Optional[str]: The ID of the created or updated file, or None if operation failed.

    Raises:
        Exception: If there is an error writing to Google Drive.
    """
    try:
        # Construct filename based on employee ID
        filename = f"{employee_id}.html"
        
        # Check if file already exists in Drive
        existing_file_id = api.check_if_file_exists_in_drive(
            filename, 
            SHARED_DRIVE_ID, 
            SHARED_DRIVE_FOLDER_ID, 
            credentials
        )

        # Create new file if it doesn't exist, otherwise update existing file
        if not existing_file_id:
            file_id = api.create_file_in_drive(
                filename, 
                SHARED_DRIVE_ID, 
                SHARED_DRIVE_FOLDER_ID, 
                signature, 
                credentials
            )
            return file_id
        else:
            api.update_file_in_drive(
                existing_file_id,
                signature,
                credentials
            )
            return existing_file_id
    except Exception as e:
        logger.error(f"Error writing signature to Drive for {employee_id}: {str(e)}")
        raise


def update_signature(employee_id: str, signature: str) -> bool:
    """
    Updates the Gmail signature for a specified employee and uploads the signature to Google Drive.

    Args:
        employee_id (str): The unique identifier (email) of the employee.
        signature (str): The new signature to be set for the employee.

    Returns:
        bool: True if the update was successful, False otherwise.

    Raises:
        Exception: If there is an error updating the signature.
    """

    try:
        logger.info(f"Updating signature for {employee_id}")

        # Get personal user credentials for the employee
        personal_credentials = api.get_credentials(
            employee_id, 
            SCOPES_PERSONAL, 
            PROJECT_ID, 
            SECRET_NAME
        )

        # Update Gmail signature using the obtained user credentials
        api.update_gmail_signature(employee_id, signature, personal_credentials.token)

        # Upload signature to Google Drive, ignore errors
        try:
            write_signature_to_drive(employee_id, signature, personal_credentials)
        except:
            pass

        return True
    except Exception as e:
        logger.error(f"Error updating signature for {employee_id}: {str(e)}")
        raise


@app.post(
    "/update-signature/", 
    response_model=SignatureResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Gmail signature",
    description="Receives a Pub/Sub message and updates the Gmail signature for the specified employee"
)
async def receive_pubsub_message(pubsub_message: PubSubMessage) -> Dict[str, str]:
    """
    Endpoint to receive Pub/Sub messages for signature updates.
    
    Args:
        pubsub_message (PubSubMessage): The Pub/Sub message containing signature data.
        
    Returns:
        Dict[str, str]: A response indicating the status of the operation.
        
    Raises:
        HTTPException: If there is an error processing the message.
    """
    try:
        # Decode and process the Pub/Sub message
        message_data = pubsub_message.message.data
        
        # Base64 decode and JSON parse the message data
        decoded_message = base64.b64decode(message_data).decode("utf-8")
        message_json = json.loads(decoded_message)
        
        # Validate the message structure
        signature_message = SignatureMessage(**message_json)
        
        # Update signature for the specified employee
        update_signature(signature_message.employee_id, signature_message.signature)
        
        return {
            "status": "success", 
            "employee_id": signature_message.employee_id
        }
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in message"
        )
    except KeyError as e:
        logger.error(f"Missing required field in message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required field: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing message: {str(e)}"
        )


if __name__ == "__main__":
    # Run the FastAPI app
    uvicorn.run(app, host="0.0.0.0", port=PORT)