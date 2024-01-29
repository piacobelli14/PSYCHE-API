import os
import psycopg2
import json
from datetime import datetime
import csv
from dotenv import load_dotenv

load_dotenv()

# Load environment variables
DB_HOST = os.environ['DB_HOST']
DB_NAME = os.environ['DB_NAME']
DB_USER = os.environ['DB_USER']
DB_PASSWORD = os.environ['DB_PASSWORD']
DB_PORT = os.environ['DB_PORT']

def connect_to_database():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )

def lambda_handler(event, context):
    # Decode the request body
    body = json.loads(event["body"])
    dataString = body["data"]
    dataArray = dataString.split(',')
    
    fields = ['timestamp', 'devID', 'accX', 'accY', 'accZ', 'gyroX', 'gyroY', 'gyroZ', 'hr', 'presence', 'battery']
    currentTimestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    dataArray.insert(0, currentTimestamp)
    data = {field: dataArray[index] if index < len(dataArray) else '0' for index, field in enumerate(fields)}
    
    if 'devID' in data and data['devID'].isdigit():
        devid = f"ST-{'0' if int(data['devID']) < 10 else ''}{data['devID']}"
        with connect_to_database() as conn:
            with conn.cursor() as cur:
                assignmentQuery = "SELECT devassigned, devassignedname FROM psyche_registereddevices WHERE devid = %s"
                cur.execute(assignmentQuery, (devid,))
                row = cur.fetchone()
                if row:
                    ptid, ptname = row
                    filePath = f"{os.getcwd()}/CurrentPatientCSVs/{ptid}-{ptname.replace(' ', '')}_RTData.csv"
                    file_exists = os.path.exists(filePath)
                    with open(filePath, 'a', newline='') as file:
                        writer = csv.writer(file)
                        if not file_exists:
                            writer.writerow(fields)
                        if int(data['presence']) != 0:
                            writer.writerow([data[field] for field in fields])
                    return {
                        "statusCode": 200,
                        "body": json.dumps(ptname)
                    }
                else:
                    return {"statusCode": 400, "body": "Invalid devID"}
    else:
        return {"statusCode": 400, "body": "Invalid devID"}

# Adjust for Vercel's expected handler signature
def handler(request):
    # Adapt to Vercel's request format if needed
    return lambda_handler(request, None)
