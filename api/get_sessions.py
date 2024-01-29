from http.server import BaseHTTPRequestHandler
import os
import json
import time

# Assume necessary imports are already here

def get_sessions(event):
    folderPath = f'/{os.getcwd()}/CurrentPatientCSVs'  # Example path
    try:
        files = os.listdir(folderPath)
        session_details = []
        for file in files:
            filePath = os.path.join(folderPath, file)
            size = os.path.getsize(filePath)
            creationTime = os.path.getctime(filePath)
            
            session_details.append({
                "name": file, 
                "sizeBytes": size,
                "creationTime": time.ctime(creationTime),
            })

        return {"statusCode": 200, "body": json.dumps({"sessions": session_details})}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"message": "Error gathering data: " + str(e)})}
