def train_op(is_experiment: bool = False) -> None:
    import pickle
    import pandas as pd
    import numpy as np
    import json
    import os
    import time
    import tensorflow as tf
    import boto3
    from minio import Minio
    from sklearn.linear_model import LogisticRegression
    from sklearn.naive_bayes import GaussianNB
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.svm import SVC
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    from sqlalchemy import create_engine
    from sqlalchemy import create_engine, Table, Column, Float, Integer, String, MetaData, ARRAY
    from sqlalchemy import select, desc, insert, text
    from io import BytesIO
    
    import psycopg2
    from psycopg2 import sql
    from sqlalchemy import create_engine
    
    def get_secret():
        secret_name = "DBCreds"
        region_name = "us-east-1"

        # Create a Secrets Manager client
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
    
        # Parse the secret string to get the credentials
        secret_dict = json.loads(secret)
        username = secret_dict['username']
        password = secret_dict['password']
        host = secret_dict['host']
        port = secret_dict['port']
        dbname = secret_dict['dbname']

        return username, password, host, port, dbname


    (user,pswd,host,port,db) = get_secret()
    
    bucket_name="intrusionpipeline"
    role_arn = 'arn:aws:iam::533267059960:role/aws-s3-access'
    session_name = 'kubeflow-pipeline-session'
    sts_client = boto3.client('sts')
    response = sts_client.assume_role(RoleArn=role_arn, RoleSessionName=session_name)
    credentials = response['Credentials']
    
    # Configure AWS SDK with temporary credentials
    s3_client = boto3.client('s3',
                      aws_access_key_id=credentials['AccessKeyId'],
                      aws_secret_access_key=credentials['SecretAccessKey'],
                      aws_session_token=credentials['SessionToken'])
    
    if(not is_experiment):
        db_details = {
            'dbname': db,
            'user': user,
            'password': pswd,
            'host': host,
            'port': port
        }



        # Connect to PostgreSQL
        try:
            conn = psycopg2.connect(**db_details)
            cursor = conn.cursor()
            print("Connected to PostgreSQL successfully.")
        except Exception as e:
            print(f"Failed to connect to PostgreSQL: {e}")
            exit()

        # Query to fetch data from the table
        try:
            fetch_query = "SELECT * FROM metadata_table_intrusion ORDER BY date DESC LIMIT 1;"
            df = pd.read_sql(fetch_query, conn)
        except Exception as e:
            print(f"Failed to fetch data: {e}")

        if(not df.empty):
            version = df['version'][0]
        else:
            version = 1
        
        folder_path = f"version{version}"
    
        cursor.close()
        conn.close()
    
        print(f"version{version}/X_train.npy")

        response = s3_client.get_object(Bucket=bucket_name, Key=f"version{version}/X_train.npy")
        data = response['Body'].read()
        X_train = np.load(BytesIO(data))
        X_train = pd.DataFrame(X_train)

        response = s3_client.get_object(Bucket=bucket_name, Key=f"version{version}/y_train.npy")
        data = response['Body'].read()
        y_train = np.load(BytesIO(data))


        response = s3_client.get_object(Bucket=bucket_name, Key=f"version{version}/X_test.npy")
        data = response['Body'].read()
        X_test = np.load(BytesIO(data))
        X_test = pd.DataFrame(X_test)

        response = s3_client.get_object(Bucket=bucket_name, Key=f"version{version}/y_test.npy")
        data = response['Body'].read()
        y_test = np.load(BytesIO(data))
    
    else:
        version = 0
        folder_path = 'experiment'
    
        response = s3_client.get_object(Bucket=bucket_name, Key=f"experiment/X_train.npy")
        data = response['Body'].read()
        X_train = np.load(BytesIO(data))
        X_train = pd.DataFrame(X_train)

        response = s3_client.get_object(Bucket=bucket_name, Key=f"experiment/y_train.npy")
        data = response['Body'].read()
        y_train = np.load(BytesIO(data))


        response = s3_client.get_object(Bucket=bucket_name, Key=f"experiment/X_test.npy")
        data = response['Body'].read()
        X_test = np.load(BytesIO(data))
        X_test = pd.DataFrame(X_test)

        response = s3_client.get_object(Bucket=bucket_name, Key=f"experiment/y_test.npy")
        data = response['Body'].read()
        y_test = np.load(BytesIO(data))
    
    # Define dataframe to store model metrics
    metrics = pd.DataFrame(columns=["Version", "Model", "Accuracy", "F1", "Precision", "Recall", "Train_Time", "Test_Time"])
    models_path = './tmp/intrusion/models'
    
    
    if not os.path.exists(models_path):
        os.makedirs(models_path)
        print(f"Folder '{models_path}' created successfully.")
    else:
        print(f"Folder '{models_path}' already exists.")
        
    
    #Logistic Regression
    start_train = time.time()
    lrc = LogisticRegression(random_state=0, max_iter=1000)
    lrc.fit(X_train, y_train)
    end_train = time.time()
    start_test = time.time()
    ypredlr = lrc.predict(X_test)
    end_test = time.time()
    accuracy = accuracy_score(y_test, ypredlr)
    f1 = f1_score(y_test, ypredlr)
    precision = precision_score(y_test, ypredlr)
    recall = recall_score(y_test, ypredlr)
    metrics.loc[len(metrics.index)] = [version,'lrc', accuracy, f1, precision, recall, end_train-start_train, end_test-start_test]
    with open('./tmp/intrusion/models/lrc.pkl', 'wb') as f:
        pickle.dump(lrc, f)
    s3_client.upload_file("tmp/intrusion/models/lrc.pkl", bucket_name, f"{folder_path}/lrc/model.pkl")
    
    
    #Random Forest Classifier
    start_train = time.time()
    rfc = RandomForestClassifier()
    rfc.fit(X_train, y_train)
    end_train = time.time()
    start_test = time.time()
    y_pred2=rfc.predict(X_test)
    end_test = time.time()
    accuracy = accuracy_score(y_test, y_pred2)
    f1 = f1_score(y_test, y_pred2)
    precision = precision_score(y_test, y_pred2)
    recall = recall_score(y_test, y_pred2)
    metrics.loc[len(metrics.index)] = [version, 'rfc', accuracy, f1, precision, recall, end_train-start_train, end_test-start_test]
    with open('./tmp/intrusion/models/rfc.pkl', 'wb') as f:
        pickle.dump(rfc, f)
    s3_client.upload_file("tmp/intrusion/models/rfc.pkl", bucket_name, f"{folder_path}/rfc/model.pkl")
    
    
    #Decision Tree
    start_train = time.time()
    dtc = DecisionTreeClassifier()
    dtc.fit(X_train, y_train)
    end_train = time.time()
    start_test = time.time()
    y_pred3=dtc.predict(X_test)
    end_test = time.time()
    accuracy = accuracy_score(y_test,y_pred3)
    f1 = f1_score(y_test, y_pred3)
    precision = precision_score(y_test, y_pred3)
    recall = recall_score(y_test, y_pred3)
    metrics.loc[len(metrics.index)] = [version, 'dtc', accuracy, f1, precision, recall, end_train-start_train, end_test-start_test]
    with open('./tmp/intrusion/models/dtc.pkl', 'wb') as f:
        pickle.dump(dtc, f)
    s3_client.upload_file("tmp/intrusion/models/dtc.pkl", bucket_name, f"{folder_path}/dtc/model.pkl")
    
    
    
#     #Support Vector Machine
#     start_train = time.time()
#     svc = SVC()
#     svc.fit(X_train, y_train)
#     end_train = time.time()
#     start_test = time.time()
#     y_pred4=svc.predict(X_test)
#     end_test = time.time()
#     accuracy = accuracy_score(y_test,y_pred4)
#     f1 = f1_score(y_test,y_pred4)
#     precision = precision_score(y_test, y_pred4)
#     recall = recall_score(y_test, y_pred4)
#     metrics.loc[len(metrics.index)] = [version, 'svc', accuracy, f1, precision, recall, end_train-start_train, end_test-start_test]
#     with open('./tmp/intrusion/models/svc.pkl', 'wb') as f:
#         pickle.dump(svc, f)
#     s3_client.upload_file("tmp/intrusion/models/svc.pkl", bucket_name, f"{folder_path}/svc/model.pkl")
    
    
    
#     #Gradient Boost
#     start_train = time.time()
#     gbc = GradientBoostingClassifier()
#     gbc.fit(X_train, y_train)
#     end_train = time.time()
#     start_test = time.time()
#     y_pred5=gbc.predict(X_test)
#     end_test = time.time()
#     accuracy = accuracy_score(y_test,y_pred5)
#     f1 = f1_score(y_test, y_pred5)
#     precision = precision_score(y_test, y_pred5)
#     recall = (recall_score(y_test, y_pred5))
#     metrics.loc[len(metrics.index)] = [version, 'gbc', accuracy, f1, precision, recall, end_train-start_train, end_test-start_test]
#     with open('./tmp/intrusion/models/gbc.pkl', 'wb') as f:
#         pickle.dump(gbc, f)
#     s3_client.upload_file("tmp/intrusion/models/gbc.pkl", bucket_name, f"{folder_path}/gbc/model.pkl")
    
    
#     #Gaussian Naive Bayes
#     start_train = time.time()
#     gnb = GaussianNB()
#     gnb.fit(X_train, y_train)
#     end_train = time.time()
#     start_test = time.time()
#     y_pred6=gnb.predict(X_test)
#     end_test = time.time()
#     accuracy = accuracy_score(y_test,y_pred6)
#     f1 = f1_score(y_test, y_pred6)
#     precision = precision_score(y_test,y_pred6)
#     recall = recall_score(y_test, y_pred6)
#     metrics.loc[len(metrics.index)] = [version, 'gnb', accuracy, f1, precision, recall, end_train-start_train, end_test-start_test]  
#     with open('./tmp/intrusion/models/gnb.pkl', 'wb') as f:
#         pickle.dump(gnb, f)
#     s3_client.upload_file("tmp/intrusion/models/gnb.pkl", bucket_name, f"{folder_path}/gnb/model.pkl")
    
    
    
#     #Artificial Neural Network
#     input_shape = [X_train.shape[1]]
#     start_train = time.time()
#     model = tf.keras.Sequential([
#         tf.keras.layers.Dense(units=64, activation='relu', input_shape=input_shape),
#         tf.keras.layers.Dense(units=64, activation='relu'),
#         tf.keras.layers.Dense(units=1, activation='sigmoid')
#     ])
#     model.build()
#     model.compile(optimizer='adam', loss='binary_crossentropy',  metrics=['accuracy'])
#     history = model.fit(X_train, y_train, validation_data=(X_test,y_test), batch_size=256, epochs=25)
#     end_train=time.time()
#     start_test = time.time()
#     y_pred7 = model.predict(X_test)
#     y_pred7 = (y_pred7 > 0.5).astype(np.int32)
#     end_test = time.time()
#     print(y_pred7)
#     accuracy = accuracy_score(y_test,y_pred7)
#     f1 = f1_score(y_test, y_pred7)
#     precision = precision_score(y_test,y_pred7)
#     recall = recall_score(y_test, y_pred7)
#     # accuracy = history.history['accuracy'][11]
#     metrics.loc[len(metrics.index)] = [version, 'ann', accuracy, f1, precision, recall, end_test-start_test, 0]
#     with open('./tmp/intrusion/models/ann.pkl', 'wb') as f:
#         pickle.dump(model, f)
#     s3_client.upload_file("tmp/intrusion/models/ann.pkl", bucket_name, f"{folder_path}/ann/model.pkl")

    if(not is_experiment):
        db_details = {
            'dbname': db,
            'user': user,
            'password': pswd,
            'host': host,
            'port': port
        }

        insert_query = """
            INSERT INTO intrusion_model_metrics (name, version, URI, in_use, accuracy, f1, precision, recall, train_time, test_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name, version) DO NOTHING;
        """
        try:
            conn = psycopg2.connect(**db_details)
            cursor = conn.cursor()
            print("Connected to PostgreSQL successfully.")

            # Iterate through DataFrame rows and insert into the table
            for index, row in metrics.iterrows():
                cursor.execute(insert_query, (
                    row['Model'], 
                    row['Version'], 
                    f"s3://intrusionpipeline/version{version}/{row['Model']}/model.pkl", 
                    False, 
                    row['Accuracy'], 
                    row['F1'], 
                    row['Precision'], 
                    row['Recall'], 
                    row['Train_Time'], 
                    row['Test_Time']
                ))

            conn.commit()
            print("Data inserted successfully.")

            cursor.close()
            conn.close()
            print("PostgreSQL connection closed.")
        except Exception as e:
            print(f"Failed to connect to PostgreSQL or insert data: {e}")
    else:
        print(metrics)
    