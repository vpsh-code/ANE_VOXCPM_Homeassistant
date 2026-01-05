import subprocess
import sys
import time
import os

def main():
    print("🚀 Starting VoxCPM-ANE Server...")
    # Starts the uvx server in the background
    server = subprocess.Popen([
        sys.executable, "-m", "voxcpmane.server", 
        "--host", "127.0.0.1", 
        "--port", "8000"
    ])
    
    # Wait for the model to load into the ANE
    print("⏳ Waiting for models to load (approx 5-10s)...")
    time.sleep(8)
    
    print("🌉 Starting Wyoming Bridge on port 10330...")
    try:
        # Runs your bridge script
        subprocess.run([sys.executable, "vox_bridge.py"])
    except KeyboardInterrupt:
        print("\n👋 Shutting down processes...")
        server.terminate()
        server.wait()

if __name__ == "__main__":
    main()
