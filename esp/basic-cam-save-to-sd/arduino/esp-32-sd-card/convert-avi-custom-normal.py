#!/usr/bin/env python3
"""
AVI Timestamp Processor

This script reads AVI video files with custom TIMS (timestamp) chunks,
extracts the embedded timestamps, overlays them on frames, and generates
a new video with proper timing based on the original timestamps.

Requirements:
- opencv-python
- numpy
- struct (built-in)
- datetime (built-in)
"""

import cv2
import numpy as np
import struct
import os
from datetime import datetime, timezone
from typing import List, Tuple, Optional
import argparse


class TimestampChunk:
    """Represents a TIMS timestamp chunk from the AVI file"""
    def __init__(self, unix_epoch_ms: int):
        self.unix_epoch_ms = unix_epoch_ms
        self.original_value = unix_epoch_ms
        
        # Determine timestamp type based on ESP32 getCurrentTimestampMs() logic
        if unix_epoch_ms > 1577836800000:  # If it's after 2020-01-01 in milliseconds
            # This looks like a proper Unix timestamp in milliseconds (NTP was available)
            self.datetime = datetime.fromtimestamp(unix_epoch_ms / 1000.0, tz=timezone.utc)
            self.is_unix_timestamp = True
            self.timestamp_type = "NTP Unix timestamp"
        else:
            # This looks like millis() - milliseconds since ESP32 boot
            # We'll create a relative datetime starting from epoch for display purposes
            self.datetime = datetime.fromtimestamp(unix_epoch_ms / 1000.0, tz=timezone.utc)
            self.is_unix_timestamp = False
            self.timestamp_type = "millis() since boot"
    
    def __str__(self):
        if self.is_unix_timestamp:
            return f"TIMS: {self.unix_epoch_ms}ms ({self.datetime.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC) [NTP]"
        else:
            # For millis() timestamps, show boot time and duration
            seconds = self.unix_epoch_ms / 1000.0
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = seconds % 60
            return f"TIMS: {self.unix_epoch_ms}ms ({hours:02d}:{minutes:02d}:{secs:06.3f} since boot) [millis()]"


class AVITimestampReader:
    """Reads AVI files and extracts custom TIMS timestamp chunks"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.file = None
        self.timestamps: List[TimestampChunk] = []
        
    def __enter__(self):
        self.file = open(self.filepath, 'rb')
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file:
            self.file.close()

    def read_timestamps(self) -> List[TimestampChunk]:
        """Extract all TIMS timestamp chunks from the AVI file"""
        self.timestamps = []

        if not self.file:
            raise ValueError("File not opened")

        self.file.seek(0)
        file_size = os.path.getsize(self.filepath)

        print(f"Scanning file of size {file_size} bytes for TIMS chunks...")

        # Method 1: Search for TIMS pattern in the entire file
        found_any = False
        position = 0

        while position < file_size - 16:  # Need at least 16 bytes for TimestampChunk
            self.file.seek(position)
            data = self.file.read(16)

            if len(data) < 16:
                break

            # Look for TIMS ID at current position
            if data[:4] == b'TIMS':
                try:
                    chunk_size = struct.unpack('<I', data[4:8])[0]

                    # Expect chunk_size to be 8 bytes for a uint64_t timestamp
                    if chunk_size == 8:
                        unix_epoch_ms = struct.unpack('<Q', data[8:16])[0]

                        # **FIX**: Assume timestamp is already in milliseconds, no scale conversion needed.
                        # We are explicitly communicating this by design.
                        if unix_epoch_ms > 0:
                            self.timestamps.append(TimestampChunk(unix_epoch_ms))
                            found_any = True
                            print(f"Found TIMS chunk at position {position}: {unix_epoch_ms} ms")
                            position += 16  # Skip past this chunk
                        else:
                            print(f"Warning: TIMS chunk at position {position} has zero or negative timestamp ({unix_epoch_ms}). Skipping.")
                            position += 1
                    else:
                        print(f"Warning: TIMS chunk at position {position} has unexpected data size {chunk_size}. Expected 8 bytes for milliseconds timestamp. Skipping.")
                        position += 1 # Move to next byte to search for TIMS ID again
                except struct.error as e:
                    print(f"Error parsing TIMS chunk at position {position}: {e}. Skipping.")
                    position += 1
            else:
                position += 1

        # Method 2: If no TIMS found, try alternative approach - look for the pattern as written by ESP32
        # This method is less robust if not explicitly using chunking, but can act as a fallback
        if not found_any:
            print("No TIMS chunks found with Method 1, trying alternative search for exact pattern...")
            self.file.seek(0)

            # Search for the hex pattern that might represent TIMS
            # The ESP32 writes: "TIMS" (0x54494D53) + size (0x08000000) + timestamp
            tims_pattern = b'TIMS\x08\x00\x00\x00'  # TIMS + size=8 in little endian

            file_content = self.file.read()
            offset = 0

            while True:
                pos = file_content.find(tims_pattern, offset)
                if pos == -1:
                    break

                # Found the pattern, extract timestamp
                if pos + 16 <= len(file_content):
                    timestamp_bytes = file_content[pos + 8:pos + 16]
                    try:
                        unix_epoch_ms = struct.unpack('<Q', timestamp_bytes)[0]

                        # **FIX**: Assume timestamp is already in milliseconds, no scale conversion needed.
                        if unix_epoch_ms > 0:
                            self.timestamps.append(TimestampChunk(unix_epoch_ms))
                            print(f"Found TIMS pattern at position {pos}: {unix_epoch_ms} ms")
                            found_any = True
                    except struct.error as e:
                        print(f"Error parsing timestamp at position {pos}: {e}")

                offset = pos + 1 # Move to the next byte after the found pattern to continue searching

        if not found_any:
            print("No TIMS chunks found. File may not contain timestamp metadata.")
            # Let's also try to dump the first few bytes to see what we're dealing with
            self.file.seek(0)
            header = self.file.read(64)
            print(f"File header (first 64 bytes): {header}")
            print(f"Header as hex: {header.hex()}")
        else:
            print(f"Found {len(self.timestamps)} TIMS chunks total")

        return self.timestamps

class VideoProcessor:
    """Processes video files with timestamp overlay and timing correction"""
    
    def __init__(self, input_path: str, output_path: str):
        self.input_path = input_path
        self.output_path = output_path
        self.timestamps: List[TimestampChunk] = []
        
    def extract_timestamps(self) -> List[TimestampChunk]:
        """Extract timestamps from the input AVI file"""
        with AVITimestampReader(self.input_path) as reader:
            self.timestamps = reader.read_timestamps()
        return self.timestamps
    
    def overlay_timestamp_on_frame(self, frame: np.ndarray, timestamp: TimestampChunk) -> np.ndarray:
        """Overlay timestamp information on a video frame"""
        # Create a copy to avoid modifying the original
        output_frame = frame.copy()
        
        # Format timestamp text based on whether it's a Unix timestamp or millis()
        if timestamp.is_unix_timestamp:
            timestamp_text = timestamp.datetime.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + ' UTC'
            unix_text = f"Unix: {timestamp.unix_epoch_ms}ms (NTP)"
        else:
            # For millis() timestamps, show time since boot in readable format
            seconds = timestamp.unix_epoch_ms / 1000.0
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = seconds % 60
            timestamp_text = f"Boot+{hours:02d}:{minutes:02d}:{secs:06.3f}"
            unix_text = f"millis(): {timestamp.unix_epoch_ms}ms"
        
        # Text properties
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.7
        color = (255, 255, 255)  # White text
        thickness = 2
        outline_color = (0, 0, 0)  # Black outline
        outline_thickness = 4
        
        # Get text size for positioning
        (text_width, text_height), baseline = cv2.getTextSize(timestamp_text, font, font_scale, thickness)
        (unix_width, unix_height), unix_baseline = cv2.getTextSize(unix_text, font, font_scale, thickness)
        
        # Position text at top-left with some padding
        padding = 10
        y_pos = padding + text_height
        
        # Draw background rectangle for better readability
        cv2.rectangle(output_frame, 
                     (padding - 5, padding - 5), 
                     (padding + max(text_width, unix_width) + 5, padding + text_height + unix_height + baseline + 15), 
                     (0, 0, 0), -1)
        
        # Draw outline (black)
        cv2.putText(output_frame, timestamp_text, (padding, y_pos), font, font_scale, outline_color, outline_thickness)
        cv2.putText(output_frame, unix_text, (padding, y_pos + text_height + 10), font, font_scale, outline_color, outline_thickness)
        
        # Draw main text (white)
        cv2.putText(output_frame, timestamp_text, (padding, y_pos), font, font_scale, color, thickness)
        cv2.putText(output_frame, unix_text, (padding, y_pos + text_height + 10), font, font_scale, color, thickness)
        
        return output_frame
    
    def calculate_frame_durations(self) -> List[float]:
        """Calculate the duration each frame should be displayed based on timestamps"""
        if len(self.timestamps) < 2:
            return [1.0 / 30.0]  # Default to 30fps if insufficient timestamp data
        
        durations = []
        for i in range(len(self.timestamps) - 1):
            duration = (self.timestamps[i + 1].unix_epoch_ms - self.timestamps[i].unix_epoch_ms) / 1000.0
            durations.append(max(duration, 0.001))  # Minimum 1ms duration
        
        # For the last frame, use the average duration
        if durations:
            avg_duration = sum(durations) / len(durations)
            durations.append(avg_duration)
        
        return durations
    
    def process_video(self) -> bool:
        """Process the input video and generate output with timestamp overlay and corrected timing"""
        
        # Extract timestamps
        print(f"Extracting timestamps from {self.input_path}...")
        timestamps = self.extract_timestamps()
        
        if not timestamps:
            print("No TIMS timestamp chunks found in the video file!")
            return False
        
        print(f"Found {len(timestamps)} timestamp chunks")
        
        # Open input video
        cap = cv2.VideoCapture(self.input_path)
        if not cap.isOpened():
            print(f"Error: Could not open video file {self.input_path}")
            return False
        
        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        print(f"Input video: {width}x{height}, {fps} fps, {total_frames} frames")
        
        # Calculate frame durations based on timestamps
        durations = self.calculate_frame_durations()
        
        # Calculate new FPS based on timestamp timing
        if durations:
            avg_duration = sum(durations) / len(durations)
            new_fps = 1.0 / avg_duration
            print(f"Calculated new FPS based on timestamps: {new_fps:.2f}")
        else:
            new_fps = fps
        
        # Setup video writer
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(self.output_path, fourcc, new_fps, (width, height))
        
        frame_index = 0
        processed_frames = 0
        
        print("Processing frames...")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Apply timestamp overlay if we have timestamp data for this frame
            if frame_index < len(timestamps):
                frame_with_timestamp = self.overlay_timestamp_on_frame(frame, timestamps[frame_index])
                
                # Write frame to output video
                # For variable frame timing, we might need to duplicate frames
                # based on the calculated duration vs target fps
                if frame_index < len(durations):
                    duration = durations[frame_index]
                    repeats = max(1, int(duration * new_fps))
                    
                    for _ in range(repeats):
                        out.write(frame_with_timestamp)
                        processed_frames += 1
                else:
                    out.write(frame_with_timestamp)
                    processed_frames += 1
            else:
                # No timestamp data for this frame, write as-is
                out.write(frame)
                processed_frames += 1
            
            frame_index += 1
            
            # Progress indicator
            if frame_index % 100 == 0:
                print(f"Processed {frame_index}/{total_frames} frames")
        
        # Cleanup
        cap.release()
        out.release()
        
        print(f"Processing complete!")
        print(f"Output video: {self.output_path}")
        print(f"Processed {processed_frames} frames from {frame_index} input frames")
        
        return True
    
    def print_timestamp_info(self):
        """Print detailed information about extracted timestamps"""
        if not self.timestamps:
            print("No timestamps found!")
            return
        
        print(f"\nTimestamp Information ({len(self.timestamps)} entries):")
        print("-" * 60)
        
        for i, ts in enumerate(self.timestamps):
            print(f"Frame {i:3d}: {ts}")
            
            if i > 0:
                time_diff = self.timestamps[i].unix_epoch_ms - self.timestamps[i-1].unix_epoch_ms
                print(f"         Time since previous: {time_diff}ms ({time_diff/1000.0:.3f}s)")
        
        if len(self.timestamps) > 1:
            total_time = self.timestamps[-1].unix_epoch_ms - self.timestamps[0].unix_epoch_ms
            avg_interval = total_time / (len(self.timestamps) - 1)
            print(f"\nSummary:")
            print(f"Total recording time: {total_time}ms ({total_time/1000.0:.3f}s)")
            print(f"Average frame interval: {avg_interval:.1f}ms ({1000.0/avg_interval:.2f} fps)")


def main():
    parser = argparse.ArgumentParser(description='Process AVI files with TIMS timestamp chunks')
    parser.add_argument('input', help='Input AVI file path')
    parser.add_argument('-o', '--output', help='Output video file path (default: input_timestamped.mp4)')
    parser.add_argument('-i', '--info', action='store_true', help='Only show timestamp information, do not process video')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found!")
        return 1
    
    if not args.output:
        base_name = os.path.splitext(args.input)[0]
        args.output = f"{base_name}_timestamped.mp4"
    
    processor = VideoProcessor(args.input, args.output)
    
    # Extract timestamps first
    timestamps = processor.extract_timestamps()
    
    if not timestamps:
        print("No TIMS timestamp chunks found in the video file!")
        return 1
    
    # Show timestamp information
    processor.print_timestamp_info()
    
    if args.info:
        return 0
    
    # Process the video
    if processor.process_video():
        print(f"\nSuccess! Output video saved as: {args.output}")
        return 0
    else:
        print("Error processing video!")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())