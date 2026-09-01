import os
import time
import subprocess
from mfrc522 import SimpleMFRC522
import RPi.GPIO as GPIO
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Disable GPIO warnings
GPIO.setwarnings(False)

def setup_browser():
    """Set up and return a configured Chrome browser instance."""
    os.environ['DISPLAY'] = ':0.0'  # Ensure the script can access the display
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--kiosk")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--noerrdialogs")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
    
    chrome_options.binary_location = "/usr/bin/chromium-browser"
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.fullscreen_window()
    return driver

def move_mouse_to_corner():
    """Move the mouse cursor to the bottom-right corner."""
    try:
        subprocess.run(['xdotool', 'mousemove', '9999', '9999'], check=True)
    except subprocess.CalledProcessError:
        print("Failed to move mouse cursor. Make sure xdotool is installed.")

def open_page(driver, url):
    """Open a page in the current browser window."""
    print(f"Opening page: {url}")
    driver.get(url)
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        move_mouse_to_corner()
    except Exception as e:
        print(f"Error loading {url}: {str(e)}")

if __name__ == "__main__":
    # URLs for different pages
    welcome_page_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/index.html'
    product_1_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/product-1.html'
    product_2_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/product-2.html'
    product_3_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/product-3.html'
    product_4_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/product-4.html'
    product_5_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/product-5.html'
    product_6_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/product-6.html'
    product_7_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/product-7.html'
    product_8_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/product-8.html'
    product_9_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/product-9.html'
    loading_url = 'file:/home/buynamics/Documents/wtp-scale-2025/final/product_pages/scale-project/loading.html'

    # Set up the browser
    driver = setup_browser()
    
    # Initialize the RFID reader
    reader = SimpleMFRC522()
    
    # Open the welcome page initially
    open_page(driver, welcome_page_url)
    current_page_url = welcome_page_url
    
    print("System ready. Place a tag near the reader.")
    last_tag_time = time.time()
    
    try:
        while True:
            try:
                # Read the tag
                id, text = reader.read_no_block()
                if id:
                    print(f"Tag detected! ID: {id}")
                    # Determine which HTML page to open based on the tag ID
                    if id == 584615582081:
                        new_page_url = product_1_url
                        print("Detected tag ID 584615582081: Opening 'Photo frame")
                    elif id == 584615516544:
                        new_page_url = product_2_url
                        print("Detected tag ID 584615516544: Opening 'Storage box")
                    elif id == 584615778716:
                        new_page_url = product_3_url
                        print("Detected tag ID 584615778716: Opening 'Abrasive sponge")
                    elif id == 584615975327:
                        new_page_url = product_4_url
                        print("Detected tag ID 584615975327: Opening 'Swivel Castor")
                    elif id == 584615516289:
                        new_page_url = product_5_url
                        print("Detected tag ID 584615516289: Opening 'Foldable Garden Saw")
                    elif id == 584608766249:
                        new_page_url = product_6_url
                        print("Detected tag ID 584608766249: Opening 'Shower Gel")
                    elif id == 584608700712:
                        new_page_url = product_7_url
                        print("Detected tag ID 584608700712: Opening 'Hardware Box")
                    elif id == 584608700712:
                        new_page_url = product_8_url
                        print("Detected tag ID 584608700712: Opening 'Garden Throwel")
                    elif id == 584608569646:
                        new_page_url = product_9_url
                        print("Detected tag ID 584608569646: Opening 'Binder")
                    else:
                        new_page_url = None
                        print("Detected unknown tag.")
                    
                    # Open a new page if necessary
                    if new_page_url and new_page_url != current_page_url:
                        open_page(driver, loading_url)  # Show loading page
                        time.sleep(14)  # Wait for 14 seconds
                        open_page(driver, new_page_url)
                        current_page_url = new_page_url
                    
                    last_tag_time = time.time()
                
                # Return to welcome page if no tag detected for more than 2 seconds
                if time.time() - last_tag_time > 1 and current_page_url != welcome_page_url:
                    print("No tag detected for 1 second. Returning to welcome page.")
                    open_page(driver, welcome_page_url)
                    current_page_url = welcome_page_url
                
                # Small sleep to prevent tight looping
                time.sleep(0.1)
            
            except KeyboardInterrupt:
                print("Script interrupted by user.")
                break
            except Exception as e:
                print(f"Error: {e}")
    
    finally:
        print("Cleaning up...")
        driver.quit()
        GPIO.cleanup()
        print("Cleanup complete. Exiting...")
