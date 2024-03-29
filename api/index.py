import os
from io import StringIO
import csv
import pandas as pd
import time
import psycopg2
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy import text
from flask import Flask, jsonify
from flask_cors import CORS
from flask import send_file, Response
from flask import request
import smtplib
import random
import hashlib
import binascii
from dotenv import load_dotenv

load_dotenv()

smtp_config = {
    'host': os.getenv('SMTP_HOST'),
    'port': int(os.getenv('SMTP_PORT')), 
    'user': os.getenv('SMTP_USER'),
    'password': os.getenv('SMTP_PASSWORD')
}
engine = create_engine(os.getenv('POSTGRES_URL'))

app = Flask(__name__)
CORS(app)

@app.route('/')
def main_page():
    return "Peter Iacobelli built this. :)"
    
@app.route('/stored-data', methods=['POST'])
def stored_data():
    deviceBatteries()
    dataString = request.data.decode()
    dataArray = dataString.split(',')
    
    fields = ['timestamp', 'devID', 'accX', 'accY', 'accZ', 'gyroX', 'gyroY', 'gyroZ', 'hr', 'presence', 'battery']
    
    currentTimestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    
    dataArray.insert(0, currentTimestamp)
    data = {field: dataArray[index] if index < len(dataArray) else '0' for index, field in enumerate(fields)}

    if 'devID' in data and data['devID'].isdigit():
        devid = f"ST-{'0' if int(data['devID']) < 10 else ''}{data['devID']}"
        assignmentQuery = text("SELECT devassigned, devassignedname FROM psyche_registereddevices WHERE devid = :devid")
        with engine.connect() as connection:
            assignmentResult = connection.execute(assignmentQuery, {'devid': devid})
            row = assignmentResult.fetchone()
            if row:
                ptid, ptname = row
                if (ptid and ptid != 'None') and (ptname and ptname != 'None') and int(data['presence']) != 0:
                    dataInsertQuery = text('''
                        INSERT INTO psyche_patientdata
                        (ptid, ptname,  timestamp, devid, accx, accy, accz, gyrox, gyroy, gyroz, hr, presence, battery)
                        VALUES (:ptid, :ptname,  :timestamp, :devid, :accx, :accy, :accz, :gyrox, :gyroy, :gyroz, :hr, :presence, :battery)
                    ''')
                    dataInsertValue = {
                        'ptid': ptid, 
                        'ptname': ptname, 
                        'timestamp': currentTimestamp, 
                        'devid': dataArray[1], 
                        'accx': dataArray[2],  
                        'accy': dataArray[3], 
                        'accz': dataArray[4], 
                        'gyrox': dataArray[5], 
                        'gyroy': dataArray[6], 
                        'gyroz': dataArray[7], 
                        'hr': dataArray[8], 
                        'presence': dataArray[9], 
                        'battery': dataArray[10]
                    }
                    connection.execute(dataInsertQuery, dataInsertValue)
                            
                return jsonify({"message": data}), 200
            else:
                return "Invalid devID", 400
    else:
        return f"Invalid devID", 400
    
@app.route('/get-sessions', methods=['GET'])
def get_sessions():
    
    try:
        session_details = [] 
        with engine.connect() as connection:
            selectUniqueIDsQuery = text('''
                SELECT ptid, MIN(ptname) AS ptname
                FROM psyche_patientdata
                GROUP BY ptid;
            ''')
            selecteUniquePatientIDsResult = connection.execute(selectUniqueIDsQuery).fetchall()

            for ptid, ptname in selecteUniquePatientIDsResult:
                patientDataQuery = text('''
                    SELECT * FROM psyche_patientdata WHERE ptid = :ptid
                ''')
                patientDataResult = connection.execute(patientDataQuery, {'ptid': ptid}).fetchall()

                output = StringIO()
                writer = csv.writer(output)
                writer.writerow([column for column in patientDataResult[0].keys()]) 
                for row in patientDataResult:
                    writer.writerow([value for value in row])

                csv_content = output.getvalue()
                size_bytes = int(len(csv_content.encode('utf-8'))) 

                session_details.append({
                    "name": f'{ptname}-{ptid}_RTData',
                    "sizeBytes": size_bytes,
                })
                
                output.close()

        return jsonify({"sessions": session_details}), 200

    except Exception as e:
        return jsonify({"message": "Error gathering data: " + str(e)}), 500
    
@app.route('/export-sessions', methods=['POST'])
def export_sessions():
    data = request.json
    fileName = data.get('fileName', '')
    ptID = fileName.split('-')[1].split('_')[0]

    try:
        with engine.connect() as connection:
            patientDataQuery = text('SELECT * FROM psyche_patientdata WHERE ptid = :ptid')
            patientDataResult = connection.execute(patientDataQuery, {'ptid': ptID})
            rows = patientDataResult.fetchall()
            if not rows:
                return jsonify({"message": "No data found."}), 404

            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(rows[0].keys()) 
            for row in rows:
                writer.writerow(row)
                
            output.seek(0)

            patientDeleteQuery = text('DELETE FROM psyche_patientdata WHERE ptid = :ptid')
            connection.execute(patientDeleteQuery, {'ptid': ptID})

            response = Response(output.getvalue(), mimetype='text/csv')
            response.headers['Content-Disposition'] = f'attachment; filename={fileName}.csv'
            return response

    except Exception as e:
        return jsonify({"message": f"Error processing request: {str(e)}"}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data['username']
    password = data['password']
    
    try:
        with engine.connect() as connection:
            loginQuery = text('SELECT salt, hashedpassword FROM psycheusers WHERE username = :username OR email = :username;')
            loginResult = connection.execute(loginQuery, {'username': username}).fetchone()

        if not loginResult:
            return jsonify({"message": "Unable to verify login info at this time. Please try again."}), 401

        storedSalt, hashedPassword = loginResult
        hashedPasswordToCheck = hashPassword(password, storedSalt)
        if hashedPasswordToCheck == hashedPassword:
            return jsonify({}), 200
        else:
            return jsonify({"message": "These login credentials are incorrect. Please try again."}), 401

    except Exception as e:
        return jsonify({"message": "Error connecting to the database. Please try again later."}), 500

@app.route('/register-user', methods=['POST'])
def register_user():
    data = request.json
    email = data.get('email')
    username = data.get('username')
    firstName = data.get('firstName')
    lastName = data.get('lastName')
    password = data.get('password')
    image = data.get(str('image'))
    
    if not all([email, username, firstName, lastName, password]):
        return jsonify({"message": "Missing required registration info."}), 400

    try:
        with engine.connect() as connection:
            userCheckQuery = text('SELECT email, username FROM psycheusers WHERE email = :email OR username = :username;')
            userCheckResult = connection.execute(userCheckQuery, {'email': email, 'username': username}).fetchall()

            emailInUse = any(user['email'] == email for user in userCheckResult)
            usernameInUse = any(user['username'] == username for user in userCheckResult)

            if emailInUse:
                return jsonify({"message": "Email is already in use."}), 409
            if usernameInUse:
                return jsonify({"message": "Username is already in use."}), 409

            salt, hashedPassword = generateSaltedPassword(password)

            userCreationValues = {
                'firstname': [firstName],
                'lastname': [lastName],
                'username': [username],
                'email': [email],
                'password': [password],
                'hashedpassword': [hashedPassword],
                'salt': [salt],
                'image': [str(image)]
            }
            userCreationResult = pd.DataFrame(userCreationValues)
            userCreationResult.to_sql('psycheusers', engine, if_exists='append', index=False)
            
        return jsonify({}), 200

    except Exception as e:
        return jsonify({"message": "Error processing request: " + str(e)}), 500

@app.route('/reset-password', methods=['POST'])
def reset_password():
    email = request.json['email']
    
    try:
        with engine.connect() as connection:
            resetVerificationQuery = text('SELECT email, password, username FROM psycheusers WHERE email = :email;')
            resetVerificationResult = connection.execute(resetVerificationQuery, {'email': email}).fetchone()

            if resetVerificationResult is None:
                return jsonify({'message': 'Email not found.'}), 401

            username = resetVerificationResult[2]
            email = resetVerificationResult[0]

            resetCode = str(random.randint(100000, 999999))
            expiration_timestamp = datetime.now() + timedelta(minutes=3)
            
            insertResetToken = text(
                "INSERT INTO psyche_resettokens (username, resettoken, expirationtimestamp) VALUES (:username, :resettoken, :expirationtimestamp);"
            )
            connection.execute(insertResetToken, {'username': username, 'resettoken': resetCode, 'expirationtimestamp': expiration_timestamp})
            
        try:
            server = smtplib.SMTP(smtp_config['host'], smtp_config['port'])
            server.starttls()
            server.login(smtp_config['user'], smtp_config['password'])

            subject = 'Password Reset Code'
            message = f'Your password reset code is: {resetCode}'
            msg = f'Subject: {subject}\n\n{message}'

            server.sendmail(smtp_config['user'], email, msg)
            server.quit()
        except Exception as e:
            return jsonify({'message': 'Unable to send verification email.'}), 501

        return jsonify({
            'message': 'Password reset code sent.',
            'resetCode': resetCode,
            'resetExpiration': expiration_timestamp.isoformat()
        }), 200

    except Exception as e:
        return jsonify({"message": "Error processing request: " + str(e)}), 500
    
@app.route('/change-password', methods=['POST'])
def change_password():
    data = request.json
    newPassword = data.get('newPassword')
    email = data.get('email')

    try:
        salt, hashedPassword = generateSaltedPassword(newPassword)

        with engine.connect() as connection: 
            updatePasswordQuery = text('''
                UPDATE psycheusers 
                SET password = :password, hashedpassword = :hashedpassword, salt = :salt 
                WHERE email = :email;
            ''')
            updatePasswordValues = {
                'password': newPassword, 
                'hashedpassword': hashedPassword, 
                'salt': salt, 
                'email': email
            }
            connection.execute(updatePasswordQuery, updatePasswordValues)

        return jsonify({}), 200

    except Exception as e:
        return jsonify({"message": "Error processing request: " + str(e)}), 500
    
@app.route('/get-patients', methods=['POST'])
def get_patients_current():
    data = request.json
    patientSet = data.get('patientTable')
    
    try:
        with engine.connect() as connection:
            if patientSet == 'archive':
                selectPatientsQuery = text('SELECT ptid, ptname, ptsex, ptage, pttag FROM psychepatientinfo_archive')
            else: 
                selectPatientsQuery = text('SELECT ptid, ptname, ptsex, ptage, pttag FROM psychepatientinfo')
            result = connection.execute(selectPatientsQuery).fetchall()

            patientInfoList = [
                {
                    'ptid': row[0],
                    'ptname': row[1],
                    'ptsex': row[2],
                    'ptage': row[3],
                    'pttag': row[4]
                } for row in result
            ]

            return jsonify(patientInfoList), 200

    except Exception as e:
        return jsonify({"message": "Error processing request: " + str(e)}), 500
    
@app.route('/enroll-patient', methods=['POST'])
def enroll_patient():
    data = request.json
    ptName = data.get('patientName')
    ptUnit = data.get('patientUnit')
    ptSex = data.get('patientSex')
    ptAge = int(data.get('patientAge'))
    ptID = data.get('patientID')

    try:
        with engine.connect() as connection:
            checkIDQuery = text("""
                SELECT ptid 
                FROM psychepatientinfo 
                WHERE ptid = :ptid
                UNION 
                SELECT ptid 
                FROM psychepatientinfo_archive 
                WHERE ptid = :ptid
            """)
            checkIDResult = connection.execute(checkIDQuery, {'ptid': ptID}).fetchone()

            if checkIDResult:
                return jsonify({"message": "Patient ID already in use"}), 400

            enrollPatientQuery = text("""
                INSERT INTO psychepatientinfo (ptid, ptname, ptsex, ptage, pttag)
                VALUES (:ptid, :ptname, :ptsex, :ptage, :pttag)
            """)
            enrollPatientValues = {
                'ptid': ptID, 
                'ptname': ptName, 
                'ptsex': ptSex, 
                'ptage': ptAge, 
                'pttag': ptUnit
            }
            
            connection.execute(enrollPatientQuery, enrollPatientValues)
            
            return jsonify({}), 200

    except Exception as e:
        return jsonify({"message": "Error processing request: " + str(e)}), 500

@app.route('/edit-patient', methods=['POST'])
def edit_patient():
    data = request.json
    ptName = data.get('patientName')
    ptUnit = data.get('patientUnit')
    ptSex = data.get('patientSex')
    ptAge = int(data.get('patientAge'))
    ptID = data.get('patientID')

    try:
        with engine.connect() as connection:
            
            editPatientQuery = text("""
                UPDATE psychepatientinfo SET ptname = :ptname, ptsex = :ptsex, ptage = :ptage, pttag = :pttag  
                WHERE ptid = :ptid;
            """)
            editPatientValues = { 
                'ptname': ptName, 
                'ptsex': ptSex, 
                'ptage': ptAge, 
                'pttag': ptUnit,
                'ptid': ptID,
            }
            
            connection.execute(editPatientQuery, editPatientValues)
            
            return jsonify({}), 200

    except Exception as e:
        return jsonify({"message": "Error processing request: " + str(e)}), 500
    
@app.route('/archive-patient', methods=['POST'])
def archive_patient():
    data = request.json
    ptID = data.get('patientID')

    try:
        with engine.connect() as connection:
            copyUserQuery = text("""
                INSERT INTO psychepatientinfo_archive
                SELECT * FROM psychepatientinfo
                WHERE ptid = :ptid
            """)
            connection.execute(copyUserQuery, {'ptid': ptID})

            deleteUserQuery = text("""
                DELETE FROM psychepatientinfo
                WHERE ptid = :ptid
            """)
            connection.execute(deleteUserQuery, {'ptid': ptID})

            return jsonify({}), 200

    except Exception as e:
        return jsonify({"message": "Error processing request: " + str(e)}), 500

@app.route('/selected-patient-placeholders', methods=['POST'])
def edit_patient_placeholders():
    data = request.json
    ptID = str(data.get('patientID'))
    
    try: 
        with engine.connect() as connection:
            patientPlaceholderQuery = text('SELECT * FROM psychepatientinfo WHERE ptid = :ptid')
            patientPlaceholderResult = connection.execute(patientPlaceholderQuery, {'ptid': ptID}).fetchall()

            selectedPatientList = patientPlaceholderResult[0]
            selectedPatientID = selectedPatientList[0]
            selectedPatientFirstName = selectedPatientList[1].split(' ')[0]
            selectedPatientLastName = selectedPatientList[1].split(' ')[-1]
            selectedPatientSex = selectedPatientList[2]
            selectedPatientAge = selectedPatientList[3]
            selectedPatientTag = selectedPatientList[4]
            
            patientPlaceholders = {
                'ptIDPlaceholder': selectedPatientID, 
                'ptFirstNamePlaceholder': selectedPatientFirstName, 
                'ptLastNamePlaceholder': selectedPatientLastName, 
                'ptSexPlaceholder': selectedPatientSex, 
                'ptAgePlaceholder': str(selectedPatientAge), 
                'ptTagPlaceholder': selectedPatientTag,
            }
            
        return jsonify(patientPlaceholders), 200
            
    except Exception as e:
        return jsonify({"message": "Error processing request: " + str(e)}), 500
    
@app.route('/get-devices', methods=['GET'])
def get_device_info(): 
    try: 
        with engine.connect() as connection: 
            deviceInformationQuery = text('SELECT * FROM psyche_registereddevices;')
            deviceInformationResult = connection.execute(deviceInformationQuery).fetchall()

            deviceInfoList = [
                {
                    "devType": str(device[0]),
                    "devID": str(device[1]),
                    "assignedTo": str(device[5]),
                    "lastAssigned": str(device[3]),
                    "battery": str(device[4])
                } for device in deviceInformationResult
            ]

            return jsonify(deviceInfoList), 200  

    except Exception as e: 
        return jsonify({"message": "Error processing request:" + str(e)}), 500
    
@app.route('/register-device', methods=['POST'])
def add_device(): 
    data = request.json
    devType = data.get('devType')
    devID = data.get('devID')
    devAssigned = 'None'
    devAssignedTime = datetime.now()
    devBattery = 100
    
    try: 
        with engine.connect() as connection: 
            
            checkIDQuery = text("""
                SELECT devid 
                FROM psyche_registereddevices 
                WHERE devid = :devid
            """)
            checkIDResult = connection.execute(checkIDQuery, {'devid': devID}).fetchone()

            if checkIDResult:
                return jsonify({"message": "Patient ID already in use"}), 400
            
            deviceEntryQuery = text('''
                                    INSERT INTO psyche_registereddevices (devtype, devid, devassigned, lastassignment, devbattery)
                                    VALUES (:devtype, :devid, :devassigned, :lastassignment, :devbattery)
                                ''')
            deviceEntryValues = {
                'devtype': devType, 
                'devid': devID, 
                'devassigned': devAssigned, 
                'lastassignment': devAssignedTime,
                'devbattery': devBattery
            }
            
            connection.execute(deviceEntryQuery, deviceEntryValues)
            
            return jsonify({}), 200
        
    except Exception as e: 
        return jsonify({"message": "Error processing request:" + str(e)}), 500
    
@app.route('/remove-device', methods=['POST'])
def remove_device(): 
    data = request.json
    devID = data.get('devID')
    
    try: 
        with engine.connect() as connection: 
            deviceRemovalQuery = text("DELETE FROM psyche_registereddevices WHERE devid = :devid")
            connection.execute(deviceRemovalQuery, {'devid': devID})
            
            return jsonify({}), 200
    
    except Exception as e: 
        return jsonify({"mesage": "Error processing request:" + str(e)}), 500
    
@app.route('/get-assignment-info', methods=['POST'])
def get_assignment_info():
    data = request.json
    ptID = data.get('ptID')

    try:
        with engine.connect() as connection:
            patientInfoQuery = text("""
                SELECT pi.ptName, rd.devid, rd.devtype
                FROM psychepatientinfo pi
                LEFT JOIN psyche_registereddevices rd ON pi.ptid = rd.devassigned AND rd.devassigned = :ptid
                WHERE pi.ptid = :ptid
            """)
            patientInfoResult = connection.execute(patientInfoQuery, {'ptid': ptID}).fetchone()
            
            if patientInfoResult:
                return jsonify({
                    "ptName": patientInfoResult[0],
                    "currentDevID": patientInfoResult[1] if patientInfoResult[1] else "None", 
                    "currentDevType": patientInfoResult[2] if patientInfoResult[2] else "None"
                }), 200
            else:
                return jsonify({"ptName": "None", "currentDevID": "None", "currentDevType": "None"}), 404

    except Exception as e:
        return jsonify({"message": "Error processing request: " + str(e)}), 500


@app.route('/swap-device', methods=['POST'])
def swap_device(): 
    data = request.json
    newDevID = data.get('newDevID')
    oldDevID = data.get('oldDevID')
    ptID = data.get('ptID')
    ptName = data.get('ptName')
    
    try: 
        with engine.connect() as connection: 
            if oldDevID != 'None': 
                deviceDeleteQuery = text("UPDATE psyche_registereddevices SET devassigned = 'None', devassignedname = 'None' WHERE devid = :devid")
                connection.execute(deviceDeleteQuery, {'devid': oldDevID})
            deviceAssignQuery = text("UPDATE psyche_registereddevices SET devassigned = :devassigned, devassignedname = :devassignedname, lastassignment = :lastassignment WHERE devid = :devid")
            deviceAssignValues = {
                'devassigned': ptID, 
                'devassignedname': ptName,
                'lastassignment': datetime.now(), 
                'devid': newDevID,
            }
            connection.execute(deviceAssignQuery, deviceAssignValues)
            
            return jsonify({}), 200
            
    except Exception as e: 
        return jsonify({"mesage": "Error processing request:" + str(e)}), 500
    
def hashPassword(entered_password, storedSalt):
    if not entered_password or not storedSalt:
        return None

    saltedPasswordToCheck = storedSalt + entered_password
    hashedPassword = hashlib.sha256(saltedPasswordToCheck.encode()).hexdigest()
    return hashedPassword

def generateSaltedPassword(password):
    salt = binascii.hexlify(os.urandom(16)).decode()
    saltedPassword = salt + password
    hashedPassword = hashlib.sha256(saltedPassword.encode()).hexdigest()
    return salt, hashedPassword
        
def deviceBatteries():
    fetchBatteryLevelsQuery = text("""
        SELECT devID, battery
        FROM (
            SELECT devID, battery,
                   ROW_NUMBER() OVER(PARTITION BY devID ORDER BY timestamp DESC) AS rn
            FROM psyche_patientdata
        ) ranked
        WHERE rn = 1
    """)

    with engine.connect() as connection:
        recentBatteryLevels = connection.execute(fetchBatteryLevelsQuery).fetchall()
        for devID, battery in recentBatteryLevels:
            if devID and battery is not None:
                devIDFormatted = f"ST-{'0' if int(devID) < 10 else ''}{devID}"
                updateBatteryQuery = text("""
                    UPDATE psyche_registereddevices
                    SET devbattery = :devbattery
                    WHERE devid = :devid;
                """)
                connection.execute(updateBatteryQuery, {'devbattery': battery, 'devid': devIDFormatted})
