# main.py
import cv2
import requests
import numpy as np
from PIL import Image
import io

# --- Configuration ---
# The direct URL to your printer's MJPEG video stream.
PRINTER_VIDEO_URL = "http://192.168.128.143:3031/video"
WINDOW_NAME = "Printer Video Stream"

def main():
    """
    Connects to the printer's video stream and displays it in a desktop window.
    Press 'q' to quit the application.
    """
    print(f"Attempting to connect to video stream at: {PRINTER_VIDEO_URL}")

    try:
        # Use stream=True to handle the live feed without loading it all into memory
        response = requests.get(PRINTER_VIDEO_URL, stream=True, timeout=10)
        
        # Raise an exception if the connection was not successful (e.g., 404 Not Found)
        response.raise_for_status()
        
        print("Successfully connected to stream. Press 'q' in the video window to quit.")
        
        # Buffer to hold the bytes for a single JPEG image
        image_bytes = b''
        
        # Iterate over the content of the response chunk by chunk
        for chunk in response.iter_content(chunk_size=1024):
            # Add the new chunk to our buffer
            image_bytes += chunk
            
            # MJPEG streams separate frames with a boundary marker.
            # We look for the start (0xff 0xd8) and end (0xff 0xd9) markers of a JPEG file.
            a = image_bytes.find(b'\xff\xd8')
            b = image_bytes.find(b'\xff\xd9')
            
            # If we have a complete frame in our buffer
            if a != -1 and b != -1:
                # Extract the JPEG data
                jpg = image_bytes[a:b+2]
                
                # The remainder of the buffer is the start of the next frame
                image_bytes = image_bytes[b+2:]
                
                try:
                    # Decode the JPEG bytes into an image using Pillow
                    pil_image = Image.open(io.BytesIO(jpg))
                    
                    # Convert the Pillow image to an OpenCV image (NumPy array)
                    # PIL uses RGB, OpenCV uses BGR, so we convert the color space
                    frame = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
                    
                    # Display the resulting frame in a window
                    cv2.imshow(WINDOW_NAME, frame)

                except Exception as e:
                    # This can happen if a frame is corrupted
                    print(f"Could not decode frame: {e}")
                    continue

            # Wait for 1 millisecond and check if the 'q' key was pressed
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Could not connect to the printer's video stream.")
        print(f"Please check the URL and your network connection. Details: {e}")

    finally:
        # Clean up and close the window when the loop is exited
        print("Closing video stream window.")
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
