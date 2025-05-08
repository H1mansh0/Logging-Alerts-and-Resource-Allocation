import pytz
import re
import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from requests import get, post
from influxdb_client import InfluxDBClient, Point, WritePrecision
from datetime import datetime

time.sleep(5)

app = FastAPI()

client = InfluxDBClient(
    url="http://influxdb:8086",
    token="infinitetoken",
    org="ucu"
)

class AlertEngine:
    def __init__(self, logger):
        self.logger = logger

    def _is_suspicious_input(self, message: str):
        input_case = None

        if not message or len(message.strip()) < 5:
            self.logger("WARNING", f"Invalid input message: '{message}'")
            input_case = "WRONG INPUT"

        if len(message) > 100:
            self.logger("WARNING", f"Input message too long: '{message}'")
            input_case = "WRONG INPUT"

        if message.isnumeric():
            self.logger("WARNING", f"Input message is number: '{message}'")
            input_case = "WRONG INPUT"

        patterns = [
            (r"\b\d{13,16}\b", "Credit card number detected", "PERSONAL INFO"),
            (r"\+?\d[\d\s\-]{7,}", "Phone number detected", "PERSONAL INFO"),
            (r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "Email address detected", "PERSONAL INFO"),
            (r"(?i)(drop\s+table|union\s+select|or\s+1=1)", "Suspicious SQL-like input detected", "FRAUD ATTEMPT"),
        ]

        for pattern, reason, case in patterns:
            if re.search(pattern, message):
                self.logger("WARNING", f"Blocked input: {reason}")
                input_case = case

        return input_case
 

    def _generate_report(self, case):
        kyiv_time = datetime.now(pytz.timezone("Europe/Kyiv"))
        filename = f"report_{kyiv_time.strftime('_%H:%M_%d_%m_%Y')}.txt"

        if case == "PERSONAL INFO":
            report_description = "Input message contains personal information"
        elif case == "FRAUD ATTEMPT":
            report_description = "Input message contains dangerous query"
        else:
            report_description = "Input message has incorrect type"

        with open(f"./error_reports/{filename}", "w") as file:
            file.write(f"Time: {kyiv_time}\nType of error: {case}\nDescription: {report_description}")

        return report_description

    def analyse_message(self, message: str):
        input_case = self._is_suspicious_input(message)

        if input_case:
            self.logger("INFO", "Report was successfully generated")
            report_description = self._generate_report(input_case) 
            return True, report_description
        
        return False, None

def send_log(log_level, message):
    point = Point("client_logs")\
        .tag("level", log_level)\
        .field("message", message)\
        .time(datetime.now(pytz.timezone("Europe/Kyiv")), WritePrecision.NS)
    
    write_api = client.write_api()
    write_api.write(bucket="logs", org="ucu", record=point)
    write_api.flush()
    write_api.close()

alert_engine = AlertEngine(send_log)
BUSINEES_URL = "http://business-service:8001"

send_log("INFO", "Client service succesfully started")

@app.get("/")
def get_description():
    send_log("INFO", "User used root endpoint")
    return {"details": "simple app with alerting, logging and celery"}

@app.get("/health")
def get_healthcheck():
    send_log("INFO", "User checked health status")
    return {"status": 200}

@app.get("/status/{task_id}")
def get_task_status(task_id: str):
    responce = get(f"{BUSINEES_URL}/status/{task_id}")
    return JSONResponse(content=responce.json())

@app.post("/process")
def submit_task(message: str):
    bad_input, info = alert_engine.analyse_message(message)

    if bad_input:
        raise HTTPException(403, info)
    
    responce = post(f"{BUSINEES_URL}/process?message={message}")
    return JSONResponse(content=responce.json())
