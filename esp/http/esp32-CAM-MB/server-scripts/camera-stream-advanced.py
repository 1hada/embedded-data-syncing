#!/usr/bin/env python3

"""
pip3 install flask flask-socketio eventlet
chmod +x camera-stream.py
sudo mv camera-stream.py /bin/camera-stream
"""
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
from io import BytesIO
import base64
import os


import ssl
import time
from PIL import Image
import paho.mqtt.client as mqtt
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
pip3 install flask flask-socketio eventlet paho-mqtt Flask Pillow ultralytics

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




# AWS IoT endpoint, client ID
AWS_IOT_ENDPOINT = "your-aws-iot-endpoint.amazonaws.com"

# Path to AWS IoT certificates and keys
CA_PATH = "/path/to/AmazonRootCA1.pem"
CERT_PATH = "/path/to/certificate.pem.crt"
KEY_PATH = "/path/to/private.pem.key"

# Create a new YOLO model from scratch
model = YOLO("yolov8n.yaml")

YOLO_MODEL_PATH = "yolov8n.pt"

# Initialize MQTT client
client = mqtt.Client(client_id="your-client-id")

# Configure TLS/SSL connection
client.tls_set(CA_PATH, certfile=CERT_PATH, keyfile=KEY_PATH, tls_version=ssl.PROTOCOL_TLSv1_2)
client.tls_insecure_set(False)

# Connect to AWS IoT
client.connect(AWS_IOT_ENDPOINT, port=8883)
client.loop_start()

# Initialize YOLO model
model = YOLO(YOLO_MODEL_PATH)  # Use the correct path to your YOLO model

# Function to publish image to AWS IoT
def publish_image(camera_id, image_bytes):
    topic = f"cameras/{camera_id}/images"
    client.publish(topic, image_bytes, qos=1)
    print(f"Published image from camera {camera_id} to topic {topic}")

def draw_on(image_bytes,coordinates = ()):
    image = Image.open(BytesIO(image_bytes))
    image_np = np.array(image)
    x1,y1 = 0,0
    if len(coordinates):
      x1,y1,x2,y2 = coordinates
      # Draw bounding box
      cv2.rectangle(image_np, (x1, y1), (x2, y2), (0, 255, 0), 2)
    # Add label
    label = f"Person"
    cv2.putText(image_np, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    _, buffer = cv2.imencode('.jpg', image_np)
    image_with_detections = buffer.tobytes()
    return image_with_detections
    


# Function to detect a person in the image using YOLO
def detect_and_draw(image_bytes):
    image_with_detections = image_bytes
    image = Image.open(BytesIO(image_bytes))
    results = model(image)
    person_detected = False
    for result in results:
        for pred in result.pred:
            if pred[5] == 'person':  # Adjust this condition based on your model's output format
                person_detected = True
                x1, y1, x2, y2 = int(pred[0]), int(pred[1]), int(pred[2]), int(pred[3])
                image_with_detections = draw_on(image_bytes,coordinates=(x1, y1, x2, y2))
    # Convert the image with detections back to bytes
    return person_detected, image_with_detections


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
        current_time = datetime.now(datetime.UTC)

        # Initialize timestamp if not present
        if camera_id not in camera_timestamps:
            camera_timestamps[camera_id] = current_time

        # Check if we should skip inference
        any_camera_seen_person = [current_time < ts for ts in camera_timestamps.values()]
        cur_has_person = current_time < camera_timestamps[camera_id]
        #if any_seen_people or current_time < camera_timestamps[camera_id]:
        if any_camera_seen_person:
            publish_image(camera_id, image_bytes)
            # edit image to see it on the hosted site
            if cur_has_person:
                image_bytes = draw_on(image_bytes)
            camera_streams[camera_id] = image_bytes
        else:
            # Detect a person in the image and draw bounding boxes
            person_detected, image_with_detections = detect_and_draw(image_bytes)
            if person_detected:
                publish_image(camera_id, image_bytes)
                camera_timestamps[camera_id] = current_time + timedelta(minutes=5)
                camera_streams[camera_id] = image_with_detections

        # Emit the updated frame to all connected clients
        socketio.emit('frame_update', {'camera_id': camera_id, 'frame': frame_data})

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
    
@app.route('/')
def display_panels_stream():
    html_template = '''
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
        <title>Image Panels</title>
        <style>
          .panel {
            display: inline-block;
            margin: 10px;
            border: 1px solid #ccc;
            padding: 10px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
          }
          img {
            max-width: 100%;
            height: auto;
          }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.0/socket.io.min.js"></script>
      </head>
      <body>
        <div>
          {% for key in camera_streams.keys() %}
            <div class="panel">
              <h3>{{ key }}</h3>
              <img id="image-{{ key }}" src="" alt="{{ key }}">
            </div>
          {% endfor %}
        </div>
        <script>
          var socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);
          socket.on('frame_update', function(data) {
            var imageElement = document.getElementById('image-' + data.camera_id);
            if (imageElement) {
              imageElement.src = 'data:image/jpeg;base64,' + data.frame;
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