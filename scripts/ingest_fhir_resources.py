import asyncio
import json
import os
from typing import Any, Callable, Coroutine
from dotenv import load_dotenv
import requests
from azure.identity import AzureCliCredential
from azure.identity.aio import get_bearer_token_provider

def get_access_token(tenant_id, client_id, client_secret, fhir_url):
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "resource": fhir_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": f"{fhir_url}/.default"
    }
    response = requests.post(token_url, headers=headers, data=data)
    response.raise_for_status()  # Raise an error for bad responses
    return response.json()["access_token"]

async def post_fhir_resource_batch(fhir_url, resource_batch, get_access_token):
    """
    Posts a batch of resources to the FHIR server.
    :param resource_batch: A bundle of resources to post."""
    url = f"{fhir_url}"
    token = await get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers, json=resource_batch)
    response.raise_for_status()  # Raise an error for bad responses
    if response.ok == False:
        raise Exception(f"Failed to post resource: {response.content}")
    return response.json()

def load_resources(path):
    """
    Yields individual resources from a file or folder.
    :param path: Path to a file or folder containing resources.
    """
    # ndjson file case
    if os.path.isfile(path):
        with open(path, "r") as file:
            for line in file:
                yield json.loads(line.strip())
    # Single file per resource case
    elif os.path.isdir(path):
        for file_name in os.listdir(path):
            file_path = os.path.join(path, file_name)
            if os.path.isfile(file_path):
                with open(file_path, "r") as file:
                    yield json.loads(file.read())
    else:
        raise ValueError(f"Invalid path: {path}")

async def post_resources_in_batches(
        file_path: str, 
        fhir_url: str, 
        resource_type: str, 
        get_access_token,
        id_map: dict = {},
        batch_size: int = 10):
    """
    Posts resources in batches to the FHIR server.
    :param file_path: Path to a file or folder containing resources.
    :param resource_type: The type of resource to post.
    :param get_access_token: The token provider for the FHIR server.
    :param batch_size: The number of resources to post in each batch."""
    if os.path.exists(file_path):
        batch_request = {
            "resourceType": "Bundle",
            "type": "batch",
            "entry": []
        }
        print(f"Posting {resource_type} resources in batches of {batch_size}...")
        count = 0
        total = 0
        responses = []
        for resource in load_resources(file_path):
            print(f"Processing resource type {resource['resourceType']} with id: {resource['id']}")
            found_id = False
            if "subject" in resource and "reference" in resource["subject"]:
                current_id = resource["subject"]["reference"].split("/")[1]
                if current_id in id_map:
                    found_id = True
                    new_id = id_map[current_id]
                    resource["subject"]["reference"] = f"Patient/{new_id}"
            if len(id_map) == 0 or found_id:
                batch_request["entry"].append({
                    "resource": resource,
                    "request": {
                        "method": "POST",
                        "url": resource_type
                    }
                })
                count += 1
                total += 1
                # If batch size is reached, post the batch and reset
                if count == batch_size:
                    response = await post_fhir_resource_batch(fhir_url, batch_request, get_access_token)
                    responses.append([batch_request, response])
                    print(f"Posted batch of {batch_size} {resource_type} resources.")
                    batch_request["entry"] = []  # Reset the batch
                    count = 0

        # Post any remaining resources in the last batch
        if batch_request["entry"] and (len(id_map) == 0 or found_id):
            response = await post_fhir_resource_batch(fhir_url, batch_request, get_access_token)
            responses.append([batch_request, response])
            print(f"Posted final batch of {len(batch_request['entry'])} {resource_type} resources.")
        print(f"Created a total of {total} {resource_type} resources.")
        return responses

def create_patient_id_map(batch_responses):
    id_map = {}
    for batch_request, batch_response in batch_responses:
        for i in range(len(batch_request['entry'])):
            request_resource = batch_request['entry'][i]['resource']
            response_resource = batch_response['entry'][i]['resource']
            id_map[request_resource["id"]] = response_resource["id"]
    return id_map

async def get_headers(bearer_token_provider: Callable[[], Coroutine[Any, Any, str]]) -> dict:
    """
    Returns the headers required for FHIR API requests.

    :return: A dictionary of headers.
    """
    return {
        "Authorization": f"Bearer {await bearer_token_provider()}",
        "Content-Type": "application/json",
    }

async def get_bearer_token_using_client_secret(tenant_id: str, client_id: str, client_secret: str, fhir_url: str) -> str:
    """
        Helper method to get a bearer token using client credentials.
    """
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "resource": fhir_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": f"{fhir_url}/.default"
    }
    response = requests.post(token_url, headers=headers, data=data)
    response.raise_for_status()  # Raise an error for bad responses
    return response.json()["access_token"]

async def main():
    
    load_dotenv("src/.env")
    credential = AzureCliCredential()
    fhir_url = os.getenv("FHIR_SERVICE_ENDPOINT")
    get_access_token = get_bearer_token_provider(credential, f"{fhir_url}/.default")

    root_folder = os.path.join(os.getcwd(), "output", "fhir_resources")
    patient_file_path = os.path.join(root_folder, "ahds", "patients")
    document_reference_file_path = os.path.join(root_folder, "ahds", "document_references")

    try:
        responses = await post_resources_in_batches(patient_file_path, fhir_url, "Patient", get_access_token, id_map={}, batch_size=10)
        
        id_map = create_patient_id_map(responses)

        responses = await post_resources_in_batches(document_reference_file_path, fhir_url, "DocumentReference",
                                  get_access_token, id_map, batch_size=10)

    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(main())