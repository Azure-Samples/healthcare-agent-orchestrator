import argparse
import json
import logging
import os
import re
import urllib.request
from typing import Any, Callable


def post_fhir_resource_batch(fhir_url: str, resource_batch: Any, auth_token: str) -> Any:
    """
    Posts a batch of resources to the FHIR server.
    :param resource_batch: A bundle of resources to post."""
    url = f"{fhir_url}"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    data = json.dumps(resource_batch).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request) as response:
        if response.status != 200:
            raise Exception(f"Failed to post resources to {url}. Status code: {response.status}")

        # Read response data
        response_body = response.read().decode('utf-8')
        return json.loads(response_body)


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


def patient_with_given_name_exists(
        fhir_url: str,
        auth_token: str,
        resource: dict) -> bool:
    """
    Checks to see if a patient with the same name already exists in the FHIR server.
    """
    patient_name = resource['name'][0]['given'][0]
    url = f"{fhir_url}/Patient?name={patient_name}"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    request = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(request) as response:
        if response.status != 200:
            raise Exception(f"Failed to fetch data from {url}. Status code: {response.status}")

        # Read patient data
        data_str = response.read().decode('utf-8')
        data = json.loads(data_str)
        patients = data.get("entry", [])

    filtered_patients = [p for p in patients if p["resource"]['name'][0]['given'][0] == patient_name]
    return len(filtered_patients) > 0


def post_resources_in_batches(
        file_path: str,
        fhir_url: str,
        resource_type: str,
        auth_token: str,
        id_map: dict = {},
        batch_size: int = 10,
        resource_exists_fn: Callable[[dict], bool] = None,
        id_map_required: bool = False):
    """
    Posts resources in batches to the FHIR server.
    :param file_path: Path to a file or folder containing resources.
    :param resource_type: The type of resource to post.
    :param get_access_token: A couroutine to get an access token.
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

            # Resource was found in the id_map or does not require id_map
            should_include = ((not id_map_required and len(id_map) == 0) or found_id)

            # Check if the resource already exists in the FHIR server
            if should_include and resource_exists_fn is not None:
                exists = resource_exists_fn(resource)
                if exists:
                    print(f"{resource_type} resource with id {resource['id']} already exists. Skipping.")
                    continue

            if should_include:
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
                    response = post_fhir_resource_batch(fhir_url, batch_request, auth_token)
                    responses.append([batch_request, response])
                    print(f"Posted batch of {batch_size} {resource_type} resources.")
                    batch_request["entry"] = []  # Reset the batch
                    count = 0
            else:
                print(
                    f"Skipping {resource_type} resource with id {resource['id']} as it does not match the id_map or already exists on the server.")

        # Post any remaining resources in the last batch
        if batch_request["entry"] and (len(id_map) == 0 or found_id):
            response = post_fhir_resource_batch(fhir_url, batch_request, auth_token)
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


def is_default_fhir_url(fhir_url: str, formatted_env_name: str) -> bool:
    """
    Checks if the given fhir_url matches the default Azure Health Data Services FHIR endpoint pattern
    for the current environment, including a 3-character alphanumeric unique suffix.

    The pattern is:
      https://ahds<env><suffix>-fhir<env><suffix>.fhir.azurehealthcareapis.com
    where <env> is AZURE_ENV_NAME and <suffix> is a 3-character alphanumeric string.

    :param fhir_url: The FHIR service endpoint URL to check.
    :return: True if it matches the default pattern, False otherwise.
    """
    if not formatted_env_name:
        return False

    # Build the regex pattern
    pattern = (
        rf"^https://ahds{re.escape(formatted_env_name)}([a-zA-Z0-9]+)-fhir{re.escape(formatted_env_name)}\1\.fhir\.azurehealthcareapis\.com/?$"
    )

    return re.match(pattern, fhir_url) is not None


def main(auth_token: str, azure_env_name: str, fhir_url: str):
    # Check if the fhir_url is the default deployed Azure Health Data Services FHIR endpoint
    formatted_env_name = azure_env_name.replace("-", "")
    if not is_default_fhir_url(fhir_url, formatted_env_name):
        print(
            f"The environment FHIR server endpoint ({fhir_url}) does not match the default deployed Azure Health Data Services FHIR endpoint pattern.")
        print(f"\nThis script is intended to ingest sample data into the test server only, exiting without changes.\n")
        return

    root_folder = os.path.join(os.getcwd(), "output", "fhir_resources")
    patient_file_path = os.path.join(root_folder, "patients")
    document_reference_file_path = os.path.join(root_folder, "document_references")

    try:
        responses = post_resources_in_batches(
            patient_file_path,
            fhir_url,
            "Patient",
            auth_token,
            resource_exists_fn=lambda r: patient_with_given_name_exists(fhir_url, auth_token, r))

        id_map = create_patient_id_map(responses)

        responses = post_resources_in_batches(
            document_reference_file_path,
            fhir_url,
            "DocumentReference",
            auth_token,
            id_map,
            batch_size=10,
            id_map_required=True)
    except:
        logging.exception("Failed to upload resources to FHIR server.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest FHIR resources into Azure Health Data Services FHIR server.")
    parser.add_argument('--auth-token', type=str, required=True, help='Authentication token for FHIR service access.')
    parser.add_argument('--azure-env-name', type=str, required=True, help='Azure environment name.')
    parser.add_argument('--fhir-url', type=str, required=True, help='FHIR service endpoint URL.')
    args = parser.parse_args()

    main(**vars(args))
