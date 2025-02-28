# Gmail Signature Update Automation

A system for automatically generating and updating Gmail signatures for Kaiser X Labs employees.

## Overview

This project consists of two main components:

1. **Sender**: Fetches employee data from Google Admin Directory, generates email signatures based on templates, and publishes them to a Google Cloud Pub/Sub topic.
2. **Receiver**: A FastAPI service that receives signature update messages from Pub/Sub, updates the user's Gmail signature, and stores a copy in Google Drive.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│ Google      │     │ Sender       │     │ Google      │     │ Receiver     │
│ Directory   │────▶│ (sender.py)  │────▶│ Pub/Sub     │────▶│ (receiver.py)│
└─────────────┘     └──────────────┘     └─────────────┘     └──────────────┘
                           │                                        │
                           ▼                                        ▼
                    ┌─────────────┐                          ┌──────────────┐
                    │ Google Docs │                          │ Gmail API    │
                    │ (Templates) │                          └──────────────┘
                    └─────────────┘                                │
                                                                   ▼
                                                             ┌──────────────┐
                                                             │ Google Drive │
                                                             └──────────────┘
```

## Components

### Sender (`sender.py`)

- Authenticates with Google APIs using service account credentials
- Retrieves all users from Google Admin Directory
- Filters out irrelevant users (suspended, archived, etc.)
- Fetches HTML signature templates from Google Docs
- Processes user data and builds personalized signatures
- Publishes signature updates to Google Cloud Pub/Sub

### Receiver (`receiver.py`)

- Runs as a FastAPI web service
- Receives signature update messages from Pub/Sub
- Updates the user's Gmail signature using Gmail API
- Stores a copy of the signature in Google Drive

### Supporting Modules

- **api.py**: Contains functions for interacting with Google APIs (Gmail, Drive, Docs, Directory)
- **data.py**: Contains functions for processing user data and building signatures

## Requirements

- Python 3.9+
- Google Cloud project with Pub/Sub, Secret Manager, and service account
- Google Workspace with admin access
- Required Python packages (see `requirements.txt`):
  - fastapi
  - uvicorn
  - google-auth
  - google-api-python-client
  - google-cloud-pubsub
  - google-cloud-secret-manager
  - requests

## Setup

1. Create a Google Cloud project
2. Create a service account with appropriate permissions
   - Required roles: "Service Account Token Creator" and "Pub/Sub Publisher"
3. Store the service account key in Google Secret Manager
4. Create a Pub/Sub topic for signature updates
5. Configure the environment variables:
   - `PROJECT_ID`: Google Cloud project ID
   - `TOPIC_ID`: Pub/Sub topic ID
   - `SECRET_NAME`: Name of the secret in Secret Manager

## Deployment

The project includes Docker configurations and Cloud Build files for deploying both components:

- `Dockerfile_sender`: Docker configuration for the sender component
- `Dockerfile_receiver`: Docker configuration for the receiver component
- `cloudbuild_sender.yaml`: Cloud Build configuration for the sender
- `cloudbuild_receiver.yaml`: Cloud Build configuration for the receiver

### Deploy Receiver on Google Cloud Run Service

```bash
# Set the project
gcloud config set project gsuite-tools-311209 

# Build and push receiver container image
gcloud builds submit --config cloudbuild_receiver.yaml 

# Deploy the receiver as a Cloud Run service
gcloud run deploy kxl-gmail-signature-update-receiver \
  --platform managed \
  --region europe-west3 \
  --allow-unauthenticated \
  --image eu.gcr.io/gsuite-tools-311209/kxl-gmail-signature-update-receiver
```

After deploying the receiver on Google Cloud Run, go to the Cloud Run service in the Google Cloud Console, navigate to Security > Service Account, and set the service account to "pushSignatures" to ensure proper permissions for the service.

Additionally, under Container > Configuration, set the "Maximum concurrent requests per instance" to 1 to prevent concurrent processing.

### Deploy Sender as Google Cloud Run Job

```bash
# Build and push the sender container image
gcloud builds submit --config cloudbuild_sender.yaml 

# Create a Cloud Run job for the sender
gcloud run jobs create kxl-gmail-signature-update-sender \
  --region europe-west3 \
  --image eu.gcr.io/gsuite-tools-311209/kxl-gmail-signature-update-sender
```

After deploying the sender on Google Cloud Run, go to the Cloud Run job in the Google Cloud Console, navigate to Security > Service Account, and set the service account to "pushSignatures" to ensure proper permissions for the service.

Next, set up a scheduler trigger for the sender job:
1. Navigate to the Cloud Run job in the Google Cloud Console
2. Go to Triggers > Add scheduler trigger
3. Set the frequency to `15 2 * * *` (runs at 02:15 every day)
4. Set the timezone to "Central European Standard Time (CET)"
5. Click "Create" to activate the scheduled trigger

## Usage

### Running the Sender

The sender is typically run as a scheduled job:

```bash
python sender.py
```

### Running the Receiver

The receiver runs as a web service:

```bash
python receiver.py
```

By default, it listens on port 8080, but this can be configured using the `PORT` environment variable.

