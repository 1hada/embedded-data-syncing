from flask import Flask, Response, request
import base64

app = Flask(__name__)

# Dictionary to store camera streams
camera_streams = {}

@app.route('/')
def index():
    return 'Hello, World!'

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
    app.run(host='0.0.0.0', port=443, ssl_context=('cert.pem', 'key.pem'))
