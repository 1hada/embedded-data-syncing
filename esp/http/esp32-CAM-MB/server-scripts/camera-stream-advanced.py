#!/usr/bin/env python3

"""
pip3 install flask flask-socketio eventlet
chmod +x camera-stream.py
sudo mv camera-stream.py /bin/camera-stream
"""
from flask import Flask, render_template_string, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from io import BytesIO
import base64
import os

import time
from functools import wraps
import base64
import datetime
import boto3

from PIL import Image
from ultralytics import YOLO
from datetime import datetime, timedelta

import cv2
import numpy as np
"""
sudo apt install python3.8-venv -y

# Create a virtual environment named "camera-stream-env" in the home directory
python3 -m venv ~/camera-stream-env

# Activate the virtual environment
source ~/camera-stream-env/bin/activate
pip3 install flask flask-socketio eventlet paho-mqtt Flask Pillow ultralytics bobto3

"""

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet')

# Dictionary to store camera streams
camera_streams = {}

# Track timestamps for each camera
camera_timestamps = {}

"""
# Redirect HTTP requests to HTTPS
@app.before_request
def redirect_to_https():
    if not request.is_secure:
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, code=301)
"""

##############################################
# logging

def rate_limited(max_per_second):
    min_interval = 1.0 / float(max_per_second)
    def decorator(func):
        last_time_called = [0.0]
        @wraps(func)
        def rate_limited_function(*args, **kwargs):
            elapsed = time.time() - last_time_called[0]
            left_to_wait = min_interval - elapsed
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            last_time_called[0] = time.time()
            return func(*args, **kwargs)
        return rate_limited_function
    return decorator

# Example usage
@rate_limited(60*5)  # Limit to 60seconds*numMinutes
def throttled_print(message):
    print(message)


##############################################
# S3
# Initialize AWS credentials and S3 client
S3_BUCKET_NAME = os.getenv('AWS_BUCKET_NAME')
S3_MAIN_PATH = os.getenv('AWS_MAIN_PATH')
s3_client = boto3.client('s3')
bytes_sent = 0
images_sent = 0
def upload_to_s3(camera_id, image_bytes):    
    # Get the current date
    current_date = datetime.now()
    # Format the date as "%year%month%day"
    day_date = current_date.strftime("%Y%m%d")
    frame_date = current_date.strftime("%Y%m%d-%S-%f")[:-3]  # Remove last 3 digits (microseconds to milliseconds)

    # Generate a unique filename or key for the S3 object
    s3_key = f"{S3_MAIN_PATH}/cameras/{day_date}/{camera_id}/images/{frame_date}.jpg"  # Modify this according to your requirement

    # Upload the image bytes to S3
    try:
        response = s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=s3_key, Body=image_bytes)
    except Exception as e:
        print(f"Failed to upload image to S3: {e}")
        return None

def upload_image(camera_id, image_bytes):
    global bytes_sent, images_sent

    # Upload image to S3
    s3_url = upload_to_s3(camera_id, image_bytes)
    if s3_url:
        bytes_sent += len(image_bytes)
        images_sent += 1
        throttled_print("Image uploaded successfully to S3:", s3_url)
    else:
        print("Failed to upload image to S3.")


##############################################
# YOLO
# Initialize YOLO model
YOLO_MODEL_PATH = os.getenv("CAMERA_STREAM_ENV_YOLO_MODEL","yolov8n.pt")

model = YOLO(YOLO_MODEL_PATH)  # Use the correct path to your YOLO model

# Function to detect a person in the image using YOLO
def detect(image_bytes):
    image = Image.open(BytesIO(image_bytes))
    results = model(image)
    person_detected = False
    for result in results:
        probabilities = result.probs.numpy().data
        class_index = probabilities.argmax()  # Get the index with the highest prob
        class_name = model.names[class_index]  # Map the index to the class name
        confidence = probabilities[class_index]
        if class_name == 'person' and confidence > 0.8:
            person_detected = True
    # Convert the image with detections back to bytes
    return person_detected


@app.route('/hello')
def index():
    return f'Hello, World! Check {camera_streams.keys()}'

@app.route('/video_stream', methods=['POST'])
def video_stream():
    try:
        # Parse the JSON data from the request
        data = request.get_json()
        camera_id = data.get('camera_id')
        frame_data = data.get('frame')

        if not camera_id or not frame_data:
            return jsonify({'error': 'Invalid payload'}), 400

        # Decode the base64 frame data
        image_bytes = base64.b64decode(frame_data)

        # Store the image bytes in the dictionary
        camera_streams[camera_id] = image_bytes

        # Get current time
        current_time = datetime.utcnow() # datetime.now(datetime.UTC) # had to use deprecated utcnow because the .now() hung

        # Initialize timestamp if not present
        if camera_id not in camera_timestamps:
            camera_timestamps[camera_id] = current_time

        # Check if we should skip inference
        any_camera_seen_person = [current_time < ts for ts in camera_timestamps.values()]
        cur_camera_seen_person = current_time < camera_timestamps[camera_id]
        if any_camera_seen_person:
            upload_image(camera_id, image_bytes)
        else:
            # Detect a person in the image and draw bounding boxes
            person_detected = detect(image_bytes)
            if person_detected:
                upload_image(camera_id, image_bytes)
                camera_timestamps[camera_id] = current_time + timedelta(minutes=5)
        camera_streams[camera_id] = frame_data

        # Emit the updated frame to all connected clients
        socketio.emit('frame_update', {'camera_id': camera_id, 'status': 'Person Detected' if cur_camera_seen_person else 'No person detected'})

        return jsonify({'message': 'Image uploaded successfully', 'camera_id': camera_id}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/image/<source>')
def serve_image(source):
    image_bytes = camera_streams.get(source)
    if image_bytes:
        return send_file(BytesIO(image_bytes), mimetype='image/jpeg')
    else:
        return "Image not found", 404

@app.route('/data')
def data_info():
    return f"Images sent {images_sent} Giga Bytes sent {bytes_sent / (1024 ** 3):.2f}"
'/')
def display_panels_stream():
    html_template = '''
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
        <title>Camera Stream Status</title>
        <style>
          table {
            width: 100%;
            border-collapse: collapse;
          }
          table, th, td {
            border: 1px solid black;
          }
          th, td {
            padding: 10px;
            text-align: left;
          }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.0/socket.io.min.js"></script>
      </head>
      <body>
        <h1>Camera Stream Status</h1>
        <table>
          <thead>
            <tr>
              <th>Camera ID</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="status-table">
            {% for key in camera_streams.keys() %}
            <tr id="row-{{ key }}">
              <td>{{ key }}</td>
              <td id="status-{{ key }}">No person detected</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        <script>
          var socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);
          socket.on('person_detected', function(data) {
            var statusElement = document.getElementById('status-' + data.camera_id);
            if (statusElement) {
              statusElement.textContent = data.status;
            }
          });
        </script>
      </body>
    </html>
    '''
    return render_template_string(html_template, camera_streams=camera_streams)

if __name__ == '__main__':
    # Start the Flask server with SSL
    socketio.run(app, host='0.0.0.0', port=5000)
