import subprocess
import sys
import time
import os

def main():
    print("🚀 Starting VoxCPM-ANE Server...")
    # We set host to 0.0.0.0 so you can also use the browser playground 
    # from other devices, but 127.0.0.1 also works for the bridge.
    server = subprocess.Popen([
        sys.executable, "-m", "voxcpmane.server", 
        "--host", "0.0.0.0", 
        "--port", "8000"
    ])
    
    print("⏳ Waiting for models to load (approx 8s)...")
    time.sleep(8)
    
    print("🌉 Starting Wyoming Bridge on port 10330 (Listening on 0.0.0.0)...")
    try:
        # This will run vox_bridge.py which is already configured 
        # to listen on 0.0.0.0:10330
        subprocess.run([sys.executable, "vox_bridge.py"])
    except KeyboardInterrupt:
        print("\n👋 Shutting down processes...")
        server.terminate()
        server.wait()

if __name__ == "__main__":
    main()