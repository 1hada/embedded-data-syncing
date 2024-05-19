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

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet')

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
    # Configuration variables
    app.config['SSL_CERTIFICATE'] = os.environ.get('SSL_CERTIFICATE')
    app.config['SSL_PRIVATE_KEY'] = os.environ.get('SSL_PRIVATE_KEY')
    
    # Start the Flask server with SSL
    socketio.run(app, host='0.0.0.0', port=5000)