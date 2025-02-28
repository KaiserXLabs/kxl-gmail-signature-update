import os
import re
import json
import logging
from typing import List, Dict, Any
from google.cloud import pubsub_v1
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.errors import HttpError

import api
import data

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Project and topic IDs for Pub/Sub
PROJECT_ID = os.getenv("PROJECT_ID", "gsuite-tools-311209")
TOPIC_ID = os.getenv("TOPIC_ID", "gmail-signature-updates")
SECRET_NAME = os.getenv("SECRET_NAME", "pushSignatures_GSUITE_ACCESS_KEYFILE")

# IDs of HTML template files in Google Drive
HTML_TEMPLATE_FILE_ID = os.getenv("HTML_TEMPLATE_FILE_ID", "1acGt7fWvaaPYSbQs9tPqNI0-OcZb4wznETkyNedsT3g")
HTML_TEMPLATE_FILE_ID_TECHNICAL_USER = os.getenv("HTML_TEMPLATE_FILE_ID_TECHNICAL_USER", "12HGPJRJIAV5LJfKTTo5x_hdC6Pn3LtNyXoItfFUJZg4")

# Scopes required for accessing Google Admin Directory and Drive APIs
SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

# Service account email
SERVICE_ACCOUNT_EMAIL = 'kaiser.soze@kaiser-x.com'

# Batch settings for Pub/Sub
PUBSUB_MAX_LATENCY = 2.0  # Maximum delay in seconds before sending a batch
PUBSUB_MAX_MESSAGES = 10  # Maximum number of messages in a batch


def check_user_for_relevance(user: Dict[str, Any]) -> bool:
    """
    Check if a user should be included in signature generation.
    
    Args:
        user: User dictionary from the Google Admin Directory API.
        
    Returns:
        True if the user is relevant for signature generation, False otherwise.
    """
    # Regular expressions to match organizational units that should be excluded
    r1 = re.compile(r"\/Deactivated.*")
    r2 = re.compile(r"\/Cloud Identities.*")
    org_unit_path = user.get("orgUnitPath", "")
    primary_email = user.get("primaryEmail", "")

    # Filter out users based on multiple criteria:
    # - suspended or archived accounts
    # - users in specific organizational units
    # - external accounts or special system accounts
    return (
        not user.get("suspended", False) and
        not user.get("archived", False) and
        not r1.match(org_unit_path) and
        not r2.match(org_unit_path) and
        org_unit_path != "/Xternal/No drive" and
        org_unit_path != "/" and
        "external" not in primary_email and
        primary_email != "kaiser.soze@kaiser-x.com" and
        primary_email != "google_tech@kaiser-x.com"
    )


def remove_irrelevant_users(users: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter out users that do not meet the relevance criteria.
    
    Args:
        users: List of user dictionaries from the Google Admin Directory API.
        
    Returns:
        Filtered list of relevant users.
    """
    relevant_users = [user for user in users if check_user_for_relevance(user)]
    return relevant_users


def send_messages_to_pubsub(messages: List[Dict[str, Any]]) -> None:
    """
    Publish messages to Google Cloud Pub/Sub.
    
    Args:
        messages: List of message dictionaries to publish.
        
    Raises:
        Exception: If there is an error publishing messages to Pub/Sub.
    """
    if not messages:
        logger.warning("No messages to publish to Pub/Sub")
        return
        
    try:
        # Configure batching settings to optimize Pub/Sub publishing
        batch_settings = pubsub_v1.types.BatchSettings(
            max_latency=PUBSUB_MAX_LATENCY,
            max_messages=PUBSUB_MAX_MESSAGES,
        )

        # Create a publisher client
        publisher = pubsub_v1.PublisherClient(batch_settings=batch_settings)

        # Create a fully qualified topic path
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        
        logger.info(f"Publishing {len(messages)} messages to Pub/Sub topic: {topic_path}")

        # Publish messages to the topic
        futures = []
        for message in messages:
            try:
                message_data = json.dumps(message).encode("utf-8")
                future = publisher.publish(topic_path, message_data)
                futures.append(future)
            except Exception as e:
                logger.error(f"Error encoding/publishing message for {message.get('employee_id', 'unknown')}: {str(e)}")

        # Wait for all the publish futures to resolve
        successful_publishes = 0
        for i, future in enumerate(futures):
            try:
                message_id = future.result()
                successful_publishes += 1
            except Exception as e:
                employee_id = messages[i].get('employee_id', 'unknown')
                logger.error(f"Error publishing message for {employee_id}: {str(e)}")
                
        logger.info(f"Successfully published {successful_publishes}/{len(messages)} messages to Pub/Sub")
    except Exception as e:
        logger.error(f"Failed to publish messages to Pub/Sub: {str(e)}")
        raise

def main() -> None:
    """
    Main function to run the Gmail signature update process.
    
    1. Authenticates with Google APIs
    2. Fetches HTML templates
    3. Retrieves and filters employees
    4. Builds signatures for each employee
    5. Sends signature update messages to Pub/Sub
    """
    try:
        logger.info("Starting Gmail signature update process")
        
        # Get the credentials for service user
        logger.info(f"Getting credentials for {SERVICE_ACCOUNT_EMAIL}")
        credentials = api.get_credentials(
            SERVICE_ACCOUNT_EMAIL, 
            SCOPES, 
            PROJECT_ID, 
            SECRET_NAME
        )

        # Fetch HTML templates
        html_template_user = api.get_text_from_doc(HTML_TEMPLATE_FILE_ID, credentials.token)
        html_template_technical_user = api.get_text_from_doc(HTML_TEMPLATE_FILE_ID_TECHNICAL_USER, credentials.token)

        # Get all employees and filter irrelevant ones
        employees = api.get_all_employees(credentials)
        logger.info(f"Retrieved {len(employees)} employees")

        relevant_employees = remove_irrelevant_users(employees)
        logger.info(f"Retrieved {len(relevant_employees)} relevant employees")

        # Build signature update messages
        messages = []
        for employee in relevant_employees:
            # Get the employee id (email)
            employee_id = employee.get("primaryEmail")

            # Process the user data
            processed_user_data = data.process_user_data(employee)

            # Build the signature
            html_template = html_template_technical_user if processed_user_data.get("technicalUser") else html_template_user
            signature = data.build_signature(html_template, processed_user_data)

            # Add the message to the list
            messages.append({"employee_id": employee_id, "signature": signature})

        # Send the messages to Pub/Sub
        send_messages_to_pubsub(messages)

            
    except Exception as e:
        logger.error(f"Gmail signature update process failed: {str(e)}")
        raise

if __name__ == "__main__":
    main()