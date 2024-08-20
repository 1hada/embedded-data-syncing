#!/usr/bin/env python3
"""
This script help sets up a machine to run inference on multiple IP cameras.
The camera's should be defined following the txt file from :
- https://docs.ultralytics.com/modes/predict/#inference-sources

Steps :
pip install ultralytics zeroconf
python3 camera-stream.py
"""

from ultralytics import YOLO
from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange
from threading import Thread
import time

import cv2
from ultralytics import YOLO
import torch

from save_stream import StreamSaver
from iphandler import IPStreamHandler

class CameraDiscovery:
    def __init__(self, output_file, service_names, interval=60):
        self.output_file = output_file
        self.service_names = service_names
        self.interval = interval
        self.discovered_ips = []
        self.zeroconf = Zeroconf()
        # Load a pretrained YOLOv8n model
        self.inference_loop_thread = Thread(target=self.inference_loop)
        self.model = YOLO("yolov8n.pt")
        self.inference_loop_thread.daemon = True
        self.running = False  # Stop the thread
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Inference device is {device}")
        self.model = YOLO("yolov8n.pt").to(device)
        self.stream_saver_dict = {}

    def on_service_state_change(self, zeroconf, service_type, name, state_change):
        if state_change is ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info:
                # Check if the service name contains any of the specified camera names
                for camera in self.service_names:
                  ip_address = ".".join(map(str, info.addresses[0]))
                  if (camera in name) and not (ip_address in self.discovered_ips):
                      print(f"Discovered {name} at IP: {ip_address}")
                      self.discovered_ips.append(f"http://{ip_address}/stream")

    def discover_services(self):
        # Start the service browser for mDNS
        ServiceBrowser(self.zeroconf, "_http._tcp.local.", handlers=[self.on_service_state_change])
        time.sleep(10)  # Allow time for discovery to complete
        print("discovery completed")

    def write_to_file(self):
        # Write discovered IP addresses to the output file
        with open(self.output_file, "w") as file:
            for ip in self.discovered_ips:
                file.write(f"{ip}\n")
                self.stream_saver_dict[ip] = StreamSaver(ip)

    def discovery_loop(self):
        while True:
            prev_ips = self.discovered_ips
            self.discovered_ips = [] # reset ips in case of restart
            self.discover_services()
            if prev_ips != self.discovered_ips:
              print("Ip's discovered has changed")
              self.write_to_file()
              if self.inference_loop_thread.is_alive():
                  self.running = False  # Stop the thread
                  self.inference_loop_thread.join()  # Wait for the thread to finish
              self.inference_loop_thread.start()
            time.sleep(self.interval)  # Wait for the next interval

    def inference_loop(self):
        self.running = True
        # Initialize a list of IPStreamHandler objects
        #streams = [IPStreamHandler(url).start() for url in self.discovered_ips]
        #print(f"Starting inference on {streams}")

        while self.running:
            print(f"About to run")
            results = self.model(self.output_file, stream=True)  # generator of Results objects
            person_found = True
            for res in results:
              #print(res)
              for box in res.boxes:
                  # Draw bounding boxes on the image
                  cls = box.cls.cpu()[0]   #: tensor([0.], device='cuda:0')
                  conf = box.conf.cpu()[0]   #: tensor([0.8933], device='cuda:0')
                  data = box.data.cpu()   #: tensor([[  0.0000,   2.1979, 637.8018, 479.2267,   0.8933,   0.0000]], device='cuda:0')
                  id = box.id   #: None
                  is_track = box.is_track   #: False
                  orig_shape = box.orig_shape   #: (480, 640)
                  shape = box.shape   #: torch.Size([1, 6])
                  xywh = box.xywh.cpu()   #: tensor([[318.9009, 240.7123, 637.8018, 477.0287]], device='cuda:0')
                  xywhn = box.xywhn.cpu()   #: tensor([[0.4983, 0.5015, 0.9966, 0.9938]], device='cuda:0')
                  xyxy = box.xyxy.cpu()   #: tensor([[  0.0000,   2.1979, 637.8018, 479.2267]], device='cuda:0')
                  xyxyn = box.xyxyn.cpu()   #: tensor([[0.0000, 0.0046, 0.9966, 0.9984]], device='cuda:0')

                  # Unpack the coordinates and convert them to integers
                  x_min, y_min, x_max, y_max = map(int, xyxy.squeeze().tolist())

                  # Draw the bounding box
                  cv2.rectangle(res.orig_img, (x_min, y_min), (x_max, y_max), (0, 255, 0), 2)

                  # Prepare label with class and confidence
                  label = f"{cls} {id}: {conf:.2f}"
                  if cls == 0:
                    person_found = True

                  # Draw the label
                  (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                  cv2.rectangle(res.orig_img, (x_min, y_min - 20), (x_min + w, y_min), (0, 255, 0), -1)
                  cv2.putText(res.orig_img, label, (x_min, y_min - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
              if person_found:
                  print("Person Found")
                  for ip, stream_saver in self.stream_saver_dict.items() :
                      stream_saver.save_stream_to_video(stream_url=ip, output_dir="video-streams", duration=60)
                  person_found = False
              # Display the image
              # TODO mutex / thread safe way to do save_stream_to_video(ip, file save path)
              #cv2.imshow(f"Detected Objects {res.path}", res.orig_img)
              if cv2.waitKey(1) == ord('q') or not self.running:
                  self.running = False
                  break
            print(results)
            print(f"looping")
        print(f"Stopping inference")


        # Close the window
        cv2.destroyAllWindows()
        """
        # Clean up
        for stream in streams:
            stream.stop()
        """
        print(f"Stopped")
        cv2.destroyAllWindows()

    def start(self):
        # Create and start the discovery thread
        thread = Thread(target=self.discovery_loop)
        thread.daemon = True
        thread.start()

        # Keep the main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Stopping discovery.")
            self.zeroconf.close()

if __name__ == "__main__":
    # Define the path for the output file
    output_file = "./list.streams"

    # Define the service names to look for
    service_names = ["Camera1", "Camera2", "Camera3"]

    # Create an instance of the CameraDiscovery class
    camera_discovery = CameraDiscovery(output_file, service_names)

    # Start the discovery process
    camera_discovery.start()

