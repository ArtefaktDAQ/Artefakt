import csv
import time
import math
import os

def generate_csv(filename="test_data.csv"):
    print(f"Starting CSV generator: {filename}")
    print("Press Ctrl+C to stop.")
    
    # Headers
    headers = ["Time from start (s)", "Channel A (V)"]
    
    # Ensure file is fresh
    if os.path.exists(filename):
        os.remove(filename)
        
    start_time = time.time()
    
    try:
        while True:
            # Open in append mode
            with open(filename, 'a', newline='') as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                
                # Write header if file is empty
                if os.path.getsize(filename) == 0:
                    writer.writerow(headers)
                
                elapsed = time.time() - start_time
                
                # Format time as HH:MM:SS
                hours, rem = divmod(int(elapsed), 3600)
                minutes, seconds = divmod(rem, 60)
                time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
                
                # Generate triangle wave pattern between 0 and 100 (integers)
                # Cycle: 0 -> 100 (100 steps) -> 0 (100 steps) = 200 steps total
                cycle_pos = int(elapsed) % 200
                if cycle_pos <= 100:
                    value = cycle_pos
                else:
                    value = 200 - cycle_pos
                
                writer.writerow([time_str, str(int(value))])
                print(f"Logged: {time_str}, {int(value)}")
            
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nGenerator stopped.")

if __name__ == "__main__":
    generate_csv()

