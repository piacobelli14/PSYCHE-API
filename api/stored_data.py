from http.server import BaseHTTPRequestHandler
import os
import psycopg2
import json
from datetime import datetime
import csv

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Load environment variables directly, assuming they are set in Vercel
        DB_HOST = os.getenv('DB_HOST')
        DB_NAME = os.getenv('DB_NAME')
        DB_USER = os.getenv('DB_USER')
        DB_PASSWORD = os.getenv('DB_PASSWORD')
        DB_PORT = os.getenv('DB_PORT')

        def connect_to_database():
            return psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=DB_PORT
            )

        # Decode the request body
        length = int(self.headers.get('Content-Length'))
        body = json.loads(self.rfile.read(length))
        dataString = body["data"]
        dataArray = dataString.split(',')
        
        fields = ['timestamp', 'devID', 'accX', 'accY', 'accZ', 'gyroX', 'gyroY', 'gyroZ', 'hr', 'presence', 'battery']
        currentTimestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        dataArray.insert(0, currentTimestamp)
        data = {field: dataArray[index] if index < len(dataArray) else '0' for index, field in enumerate(fields)}
        
        response = {}
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
                        response = {"statusCode": 200, "body": json.dumps(ptname)}
                    else:
                        response = {"statusCode": 400, "body": "Invalid devID"}
        else:
            response = {"statusCode": 400, "body": "Invalid devID"}
        
        self.send_response(response["statusCode"])
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(response["body"].encode())
