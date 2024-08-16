import cv2
import os
from datetime import datetime

def save_stream_to_video(stream_url, output_dir, duration=60):
    # Create the directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Get the current date and time for the filename
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f"{output_dir}/stream_{timestamp}.mp4"

    # Capture the stream
    cap = cv2.VideoCapture(stream_url)

    # Get the video stream properties
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Define the codec and create VideoWriter object
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filename, fourcc, fps, (width, height))

    # Set a timer to stop recording after the specified duration (in seconds)
    start_time = datetime.now()

    while (datetime.now() - start_time).seconds < duration:
        ret, frame = cap.read()

        if not ret:
            print("Failed to grab frame")
            break

        # Write the frame to the video file
        out.write(frame)

        """
        # Display the frame (optional)
        cv2.imshow('Stream', frame)

        # Stop if the 'q' key is pressed
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        """
    # Release everything if the job is finished
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    print(f"Video saved: {filename}")

if __name__ == "__main__":
    # Example usage
    stream_url = 'http://127.0.0.1'  # Replace with your stream URL
    output_dir = './videos'  # Replace with your desired output directory
    save_stream_to_video(stream_url, output_dir)