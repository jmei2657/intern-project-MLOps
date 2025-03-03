from flask import Flask, request, render_template_string
import pandas as pd
import psycopg2
import boto3
import json
import signal
import sys

app = Flask(__name__)

# Define the HTML template as a string
template = '''
<!doctype html>
<html lang="en">
  <head>
    <title>HITL phishing</title>
  </head>
  <body>
    <h1>Prediction Result</h1>
    <h3> Data: </h3>
    <p>{{ message1|safe }}</p>
    <p>{{ message2|safe }}</p>
    <h3> Is this correct? </h3>
    <form method="post">
      <button name="action" type="submit" value="correct">Yes</button>
      <button name="action" type="submit" value="incorrect">No</button>
    </form>
    <h3> Total Reviewed: </h3>
    <p> {{total|safe}} </p>
    <h3> Correct Predictions: </h3>
    <p> {{yes_count|safe}} </p>
    <h3> Incorrect Predictions: </h3>
    <p> {{no_count|safe}} </p>

  </body>
</html>
'''

total = 0
yes_count = 0
no_count = 0

# Function to get the database credentials from AWS Secrets Manager
def get_secret():
    secret_name = "DBCreds"
    region_name = "us-east-1"

    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        raise e

    secret = get_secret_value_response['SecretString']
    secret_dict = json.loads(secret)
    username = secret_dict['username']
    password = secret_dict['password']
    host = secret_dict['host']
    port = secret_dict['port']
    dbname = secret_dict['dbname']

    return username, password, host, port, dbname

# Function to fetch and process the data
def fetch_and_process_data():
    (user, pswd, host, port, db) = get_secret()

    try:
        conn = psycopg2.connect(
            dbname=db,
            user=user,
            password=pswd,
            host=host,
            port=port
        )
        cursor = conn.cursor()
    except Exception as e:
        return None, f"Failed to establish connection: {e}"

    fetch_query = "SELECT md.*,mo.outcome as prediction FROM phishing_data as md join phishing_outcomes mo on mo.uid=md.uid WHERE md.outcome = 2 limit 1;"
    try:
        df = pd.read_sql(fetch_query, conn)
        df = df.head()
    except Exception as e:
        conn.close()
        return None, f"Failed to fetch data: {e}"

    message1 = ""
    try:
        insert_query = """
        INSERT INTO phishing_outcomes (uid, outcome)
        VALUES (%s, %s)
        """
        update_query = """
        UPDATE phishing_data
        SET outcome = %s
        WHERE uid = %s
        """
        
        for index, row in df.iterrows():
            message1 = f"row {row}.<br>"
            message1 += f"UID {row['uid']} already exists in phishing_outcomes with outcome {row['prediction']}.<br>"
            print(message1)
            
            #cursor.execute(update_query, (row['outcome'], row['uid']))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        message1 = f"Failed to insert/update data: {e}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return message1, None

# Function to handle the POST request actions
def handle_post_action(action):
    global total, yes_count, no_count
    (user, pswd, host, port, db) = get_secret()
    try:
        conn = psycopg2.connect(
            dbname=db,
            user=user,
            password=pswd,
            host=host,
            port=port
        )
        cursor = conn.cursor()
    except Exception as e:
        return f"Failed to establish connection: {e}"
    
   
    

    try:
        select_query = "SELECT mo.uid,mo.outcome FROM phishing_data as md join phishing_outcomes mo on mo.uid=md.uid WHERE md.outcome = 2 limit 1;"
        cursor.execute(select_query)
        rows = cursor.fetchall()
        print(rows)
        
        message2 = ""
        for row in rows:
            uid, outcome = row
            
            if action == 'correct':
                yes_count += 1 
                print(yes_count)
                print("yes pressed")
                update_query = "UPDATE phishing_data SET outcome = %s WHERE uid = %s"
                cursor.execute(update_query, (outcome, uid))
                message2 = " Yes Data Updated Pressed"

            elif action == 'incorrect':
                no_count += 1
                print(no_count)
                print("no pressed")
                update_query = "UPDATE phishing_data SET outcome = %s WHERE uid = %s"
                cursor.execute(update_query, (1 - outcome, uid))  # Assuming binary outcome, flipping 0 to 1 and 1 to 0

                message2 = " No Data Updated Pressed"
            total += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        message2 = f"Failed to update/delete data: {e}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    
    return message2

@app.route('/', methods=['GET', 'POST'])
def index():
    global total, yes_count, no_count
    message1, error = fetch_and_process_data()
    message2 = ""
    
    
    if request.method == 'POST':
        action = request.form['action']
        message2  = handle_post_action(action)
        message1, error = fetch_and_process_data()
        
    if error:
        message1 = error

    return render_template_string(template, message1=message1, message2=message2, total=total, yes_count=yes_count, no_count=no_count)

def signal_handler(sig, frame):
    print('Shutting down the server...')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

if __name__ == '__main__':
    try:
        app.run(debug=True, host='0.0.0.0', port=5056)
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)