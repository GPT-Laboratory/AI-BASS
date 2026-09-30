import subprocess
import sys

print("Running testdata.py...")
result = subprocess.run([sys.executable, "testdata.py"])  # returns CompletedProcess
print(f"testdata.py exited with code {result.returncode}")

print("Database initialization complete.")