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
from functools import wraps

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
# MQTT
# AWS IoT endpoint, client ID
AWS_IOT_ENDPOINT = os.getenv("CAMERA_STREAM_ENV_AWS_IOT_ENDPOINT")

# Path to AWS IoT certificates and keys
AWS_ROOTCA_CERTIFICATE = os.getenv("CAMERA_STREAM_ENV_AWS_ROOTCA_CERTIFICATE")
AWS_SSL_CERTIFICATE = os.getenv("CAMERA_STREAM_ENV_AWS_SSL_CERTIFICATE")
AWS_SSL_PRIVATE_KEY = os.getenv("CAMERA_STREAM_ENV_AWS_SSL_PRIVATE_KEY")
AWS_CLIENT_ID = os.getenv("CAMERA_STREAM_ENV_AWS_CLIENT_ID")

YOLO_MODEL_PATH = os.getenv("CAMERA_STREAM_ENV_YOLO_MODEL","yolov8n.pt")

# Initialize MQTT client
print(f"MQTT service will publish to {AWS_CLIENT_ID}")
client = mqtt.Client(client_id=AWS_CLIENT_ID)

# Define the on_connect callback
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to AWS IoT")
    else:
        print(f"Failed to connect, return code {rc}")

# Define the on_publish callback
def on_publish(client, userdata, mid):
    print(f"Message {mid} has been published.")

# Assign the callback functions
client.on_connect = on_connect
client.on_publish = on_publish

# Connect to AWS IoT
client.connect(AWS_IOT_ENDPOINT, port=8883)
client.loop_start()

##############################################
# YOLO
# Initialize YOLO model
model = YOLO(YOLO_MODEL_PATH)  # Use the correct path to your YOLO model



# Function to publish image to AWS IoT
def publish_image(camera_id, image_bytes):
    topic = f"cameras/{camera_id}/images"
    msg_info = client.publish(topic, image_bytes, qos=1)

    # Check if the publish was successful
    if msg_info.rc == mqtt.MQTT_ERR_SUCCESS:
        throttled_print(f"Message {msg_info.mid} queued successfully")
    else:
        print(f"Failed to queue message, return code: {msg_info.rc}")

    # Wait for the publish to complete
    msg_info.wait_for_publish()
    throttled_print("Publish completed")


def draw_on(image_bytes,coordinates = ()):
    image = Image.open(BytesIO(image_bytes))
    image_np = np.array(image)

    if len(coordinates):
      x1,y1,x2,y2 = coordinates
      # Draw bounding box
      cv2.rectangle(image_np, (x1, y1), (x2, y2), (0, 255, 0), 2)
    # Add label
    label = f"Person"
    # Add label in the center of the image
    font_scale = 1.5
    font_thickness = 2
    text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)[0]
    text_x = (image_np.shape[1] - text_size[0]) // 2
    text_y = (image_np.shape[0] + text_size[1]) // 2
    cv2.putText(image_np, label, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 0), font_thickness)
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
        current_time = datetime.utcnow() # datetime.now(datetime.UTC) # had to use deprecated utcnow because the .now() hung

        # Initialize timestamp if not present
        if camera_id not in camera_timestamps:
            camera_timestamps[camera_id] = current_time

        # Check if we should skip inference
        any_camera_seen_person = [current_time < ts for ts in camera_timestamps.values()]
        cur_has_person = current_time < camera_timestamps[camera_id]
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