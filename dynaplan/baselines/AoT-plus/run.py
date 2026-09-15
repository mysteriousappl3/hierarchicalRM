"""Run script for the AoT+ Planning System."""
import os
import subprocess
import sys

if __name__ == "__main__":
    # Run the Streamlit app
    print("Starting AoT+ Planning System...")
    subprocess.run([sys.executable, "-m", "streamlit", "run", "src/app.py"]) 