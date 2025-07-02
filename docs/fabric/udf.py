import fabric.functions as fn
import json
import logging

udf = fn.UserDataFunctions()

def get_patient_id_map(lakehouseClient: fn.FabricLakehouseClient) -> dict:
    """
    Retrieves a list of patient IDs from the Lakehouse.
    """
    connection = lakehouseClient.connectToSql()
    cursor = None
    try:
        patient_query = """SELECT DISTINCT TOP 10 [id],[name_string]
            FROM [healthcare1_msft_silver].[dbo].[Patient];"""

        cursor = connection.cursor()
        cursor.execute(patient_query)

        results = { json.loads(result[1])[0]['given'][0] : result[0] for result in cursor}
        logging.info(json.dumps(results, indent=2))
        return results
    finally:
        if cursor:
            cursor.close()
        connection.close()

@udf.connection(argName="myLakehouse", alias="FHIR")
@udf.function()
def get_patients_by_id(myLakehouse: fn.FabricLakehouseClient) -> list:
    """
    Retrieves a list of patient IDs from the Lakehouse.
    """
    connection = myLakehouse.connectToSql()
    cursor = None
    try:
        patient_query = """SELECT DISTINCT TOP 10 [id],[name_string]
            FROM [healthcare1_msft_silver].[dbo].[Patient];"""

        cursor = connection.cursor()
        cursor.execute(patient_query)

        patient_ids = [json.loads(result[1])[0]['given'][0] for result in cursor]
        return {"ids": patient_ids}
    finally:
        if cursor:
            cursor.close()
        connection.close()

@udf.connection(argName="myLakehouse", alias="FHIR")
@udf.function()
def get_clinical_notes_by_patient_id(myLakehouse: fn.FabricLakehouseClient, patientId: str) -> list:
    """
    Retrieves clinical note metadata for a given patient ID.
    """
    connection = myLakehouse.connectToSql()
    cursor = None
    try:
        patient_id_map = get_patient_id_map(myLakehouse)
        resolved_patient_id = patient_id_map[patientId] if patientId in patient_id_map else patientId

        logging.info(f"resolved patient id: {resolved_patient_id}")
        document_reference_query = f"""SELECT TOP 1000 [id],[subject_string]
            FROM [healthcare1_msft_silver].[dbo].[DocumentReference];"""
        cursor = connection.cursor()
        cursor.execute(document_reference_query)

        note_data = []
        for row in cursor:
            try:
                note_data.append({"id": row[0], "subject": json.loads(row[1])})
            except Exception as e:
                logging.error(e)

        logging.info(f"Valid note datas: {len(note_data)}")

        retrieved_notes = []
        for note in note_data:
            logging.info(json.dumps(note_data, indent=2))
            note_subject = note["subject"]["id"].split("/")[-1]
            if note_subject == resolved_patient_id:
                retrieved_notes.append(note["id"])

        return retrieved_notes
    finally:
        if cursor:
            cursor.close()
        connection.close()

@udf.connection(argName="myLakehouse", alias="FHIR")
@udf.function()
def get_clinical_note_by_patient_id(myLakehouse: fn.FabricLakehouseClient, noteId: str) -> dict:
    """
    Retrieves the content of a clinical note for a given patient ID and note ID.
    """
    connection = myLakehouse.connectToSql()
    cursor = None
    try:
        query = f"""SELECT [id],[content_string],[subject_string]
            FROM [healthcare1_msft_silver].[dbo].[DocumentReference] WHERE id = '{noteId}';"""
        cursor = connection.cursor()
        cursor.execute(query)

        note_data = []
        for row in cursor:
            try:
                note_data.append({"id": row[0], "content": json.loads(row[1])})
            except Exception as e:
                logging.error(e)

        logging.info(f"Valid note datas: {len(note_data)}")

        return {"content": note_data[0]["content"]}if len(note_data) > 0 else {}

    finally:
        if cursor:
            cursor.close()
        connection.close()