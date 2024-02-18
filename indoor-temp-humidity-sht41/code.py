""""
Pi Zero Edge Environment Sensor
Craig Bennett - 2023
"""

import asyncio
import board
import busio
import os
import socketpool
import ssl
import time
import wifi

import adafruit_ntp
import adafruit_sht4x
import adafruit_requests as requests

# Set data collection and reporting globals from settings
SENSOR_SAMPLING_INTERVAL = os.getenv('SENSOR_SAMPLING_INTERVAL')
REPORTING_INTERVAL_SECONDS = os.getenv('REPORTING_INTERVAL_SECONDS')

# Initialize the I2C bus
# Pi Cowbell board has SDA at GP4 and SCL at GP5
i2c = busio.I2C(scl=board.GP5, sda=board.GP4)

# Initialize the SHT41 sensor
sht = adafruit_sht4x.SHT4x(i2c)
print("Found SHT4x with serial number", hex(sht.serial_number))

# Set high precision mode with no heat
sht.mode = adafruit_sht4x.Mode.NOHEAT_HIGHPRECISION
print("Current mode is: ", adafruit_sht4x.Mode.string[sht.mode])

# Load WiFi credentials from settings.toml
WIFI_SSID = os.getenv('WIFI_SSID')
WIFI_PASSWORD = os.getenv('WIFI_PASSWORD')

# Setup wifi socketpool
pool = socketpool.SocketPool(wifi.radio)

# Global sensor variables
SHT41_TEMPERATURE = None
SHT41_RELATIVE_HUMIDITY = None

# Load InfluxDB details and create request boilerplate
INFLUXDB_URL_BASE = os.getenv('INFLUXDB_URL_BASE')
INFLUXDB_ORG = os.getenv('INFLUXDB_ORG')
INFLUXDB_BUCKET = os.getenv('INFLUXDB_BUCKET')
INFLUXDB_TOKEN = os.getenv('INFLUXDB_TOKEN')

# This is the location of the sensor in the house
INFLUXDB_MEASUREMENT = os.getenv('INFLUXDB_MEASUREMENT')

# Construct the full InfluxDB URL with org and bucket parameters
INFLUXDB_URL = f"{INFLUXDB_URL_BASE}?org={INFLUXDB_ORG}&bucket={INFLUXDB_BUCKET}"

HEADERS = {
    "Authorization": f"Token {INFLUXDB_TOKEN}",
    "Content-Type": "application/json"
}

# -------------------------------------------------------------------------------

# Connect to WiFi
async def wifi_connect():
    """Connect (or reconnect) to the wifi network"""

    while True:
        if not wifi.radio.connected:
            print("Attempting to connect to WiFi...")
            try:
                wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
                print(f"Connected to {WIFI_SSID}")
            except (ConnectionError, wifi.RadioError) as error:
                print("Failed to connect:", error)
                await asyncio.sleep(10)
        else:
            await asyncio.sleep(60)


async def ntp_time_sync():
    """Get the current time using NTP"""

    while not wifi.radio.connected:
        await asyncio.sleep(1)

    ntp = adafruit_ntp.NTP(pool, tz_offset=-7)

    while True:
        try:
            #print("Syncing time...")
            current_time_struct = ntp.datetime
            formatted_time = f"{current_time_struct.tm_year}-{current_time_struct.tm_mon:02d}-{current_time_struct.tm_mday:02d} {current_time_struct.tm_hour:02d}:{current_time_struct.tm_min:02d}:{current_time_struct.tm_sec:02d}"
            #print(f"Time synchronized: {formatted_time}")
        except Exception as error:
            print("Failed to sync time:", error)
        await asyncio.sleep(3600)
        
    
async def read_sht41():
    """Read SHT41 temperature and humidity into global variables"""

    global SHT41_TEMPERATURE
    global SHT41_RELATIVE_HUMIDITY
    
    while True:
        try:
            temperature, relative_humidity = sht.measurements
            # Hold the temperature in Fahrenheit
            SHT41_TEMPERATURE = temperature * (9/5) + 32
            SHT41_RELATIVE_HUMIDITY = relative_humidity
        except RuntimeError as error:
            print("SHT41 sensor error:", error.args[0])
        await asyncio.sleep(SENSOR_SAMPLING_INTERVAL)
        


async def send_data_to_influxdb():
    """Send data to InfluxDB v2 server"""

    while not wifi.radio.connected:
        await asyncio.sleep(1)
        
    ssl_context = ssl.create_default_context()
    http_session = requests.Session(pool, ssl_context)
    
    while True:
        if None not in (SHT41_TEMPERATURE, SHT41_RELATIVE_HUMIDITY):
            data = f"{INFLUXDB_MEASUREMENT},device=sht41 temperature={SHT41_TEMPERATURE},relative_humidity={SHT41_RELATIVE_HUMIDITY}"
            try:
                response = http_session.post(INFLUXDB_URL, headers=HEADERS, data=data)
                if response.status_code == 204:
                    print("Environment data sent to InfluxDB successfully!")
                else:
                    print("Failed to send environment data to InfluxDB:", response.text)
                response.close()
            except Exception as error:
                print("Error sending environment data to InfluxDB:", error)
                
        await asyncio.sleep(REPORTING_INTERVAL_SECONDS)
        
        
async def main():
    """ Main loop to print the temperature every second """

    print("Starting async tasks...")
    asyncio.create_task(read_sht41())
    asyncio.create_task(wifi_connect())
    asyncio.create_task(ntp_time_sync())
    
    # Wait one minute before sending data to InfluxDB
    # Some sensors have a spike when they first turn on
    # Let things settle before we ship data out
    await asyncio.sleep(60)
    print("Starting async InfluxDB data transmission")
    asyncio.create_task(send_data_to_influxdb())
    
    while True:
        await asyncio.sleep(1)

asyncio.run(main())
