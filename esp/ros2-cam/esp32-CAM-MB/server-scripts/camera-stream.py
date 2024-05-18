#!/usr/bin/env python3

"""
pip3 install flask
chmod +x camera-stream.py
sudo mv camera-stream.py /bin/camera-stream
"""
from flask import Flask, Response, request, redirect

import os
import base64

app = Flask(__name__)

# Dictionary to store camera streams
camera_streams = {}

"""
# Redirect HTTP requests to HTTPS
@app.before_request
def redirect_to_https():
    if not request.is_secure:
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, code=301)
"""

@app.route('/')
def index():
    return f'Hello, World! Check {camera_streams.keys()}'

@app.route('/video_stream', methods=['POST'])
def video_stream():
    # Get the camera ID from the request
    camera_id = request.headers.get('X-Camera-ID')
    
    # Get the frame data from the request
    frame_data = request.form.get('frame')

    try :
        # Decode base64-encoded frame data
        frame_bytes = base64.b64decode(frame_data)

        # Store the frame data in the dictionary
        camera_streams[camera_id] = frame_bytes
        return 'Frame received for camera {}'.format(camera_id)
    except Exception as e:
        print(f"Invalid post due to {e}")
        return f"Exception with request {e}"

@app.route('/stream/<string:camera_id>')
def stream(camera_id):
    # Check if camera ID exists in the dictionary
    if camera_id in camera_streams:
        # Send the stored frame data as response
        return Response(camera_streams[camera_id], mimetype='image/jpeg')
    else:
        return 'Camera {} not found'.format(camera_id)


@app.route('/stream_basic')
def stream_basic():
    camera_id = "source_1"
    # Check if camera ID exists in the dictionary
    if camera_id in camera_streams:
        # Send the stored frame data as response
        return Response(camera_streams[camera_id], mimetype='image/jpeg')
    else:
        return 'Camera {} not found'.format(camera_id)


if __name__ == '__main__':
    # Configuration variables
    app.config['SSL_CERTIFICATE'] = os.environ.get('SSL_CERTIFICATE')
    app.config['SSL_PRIVATE_KEY'] = os.environ.get('SSL_PRIVATE_KEY')
    
    # Run Flask app with SSL/TLS
    app.run(host='0.0.0.0', port=5000)#, ssl_context=(app.config['SSL_CERTIFICATE'], app.config['SSL_PRIVATE_KEY']))
