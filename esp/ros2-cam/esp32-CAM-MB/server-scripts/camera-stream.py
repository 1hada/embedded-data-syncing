#!/usr/bin/env python3

"""
pip3 install flask
chmod +x camera-stream.py
sudo mv camera-stream.py /bin/camera-stream
"""
from flask import Flask, Response, request, redirect

from gunicorn.app.base import BaseApplication
from gunicorn.config import Config

class FlaskApp(BaseApplication):
    def __init__(self, app, options={}):
        self.options = options 
        self.application = app
        super().__init__()

    def load_config(self):
        config = Config(self.options)
        for key, value in config.settings.items():
            self.cfg.set(key, value)

    def load(self):
        return self.application

import ssl
import socket
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

    # Decode base64-encoded frame data
    frame_bytes = base64.b64decode(frame_data)

    # Store the frame data in the dictionary
    camera_streams[camera_id] = frame_bytes

    return 'Frame received for camera {}'.format(camera_id)

@app.route('/stream/<string:camera_id>')
def stream(camera_id):
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
   
    # Gunicorn options
    options = {
        'bind': '0.0.0.0:443',
        'worker_class': 'sync',
        'certfile': app.config['SSL_CERTIFICATE'],
        'keyfile': app.config['SSL_PRIVATE_KEY'] ,
    }
    # gunicorn -b 0.0.0.0:443 -w 4 -k gevent --certfile $SSL_CERTIFICATE --keyfile $SSL_PRIVATE_KEY camera-stream:app

    app.run(ssl_context=(app.config['SSL_CERTIFICATE'], app.config['SSL_PRIVATE_KEY']))