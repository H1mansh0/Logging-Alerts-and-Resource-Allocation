import time
import random
from fastapi import FastAPI, HTTPException
from influxdb_client import InfluxDBClient, Point, WritePrecision
from datetime import datetime, timezone
from celery import Celery
from celery.result import AsyncResult

# WAIT FOR ALL OTHER SERVICES TO START
time.sleep(5)

app = FastAPI()

client = InfluxDBClient(
    url="http://influxdb:8086",
    token="infinitetoken",
    org="ucu"
)

REDIS_URL = "redis://redis:6379/0"

celery_app = Celery(
    'tasks',
    broker=REDIS_URL,
    backend=REDIS_URL
)

celery_app.conf.update(
    task_track_started=True,
    result_expires=3600,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

def send_log(log_level, message):
    point = Point("business_logs")\
        .tag("level", log_level)\
        .field("message", message)\
        .time(datetime.now(timezone.utc), WritePrecision.NS)
    
    write_api = client.write_api()
    write_api.write(bucket="logs", org="ucu", record=point)
    write_api.flush()
    write_api.close()

@celery_app.task(bind=True, name='analyse_user_request')
def analyse_user_request(self, message: str):
    self.update_state(state='IN_PROGRESS')
    result = None
    
    try:
        time.sleep(10)
        result = (
            {"message": f"The size of message: {len(message)}"}
            if random.random() < 0.5
            else {"message": f"Amount of words: {len(message.split())}"}
        )
        return result

    except Exception as e:
        self.update_state(state='FAILED', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        raise HTTPException(status_code=500, detail="Internal analysis error")

@app.get("/")
def get_description():
    send_log("INFO", "User use root endpoint")
    return {"details": "business part of simple app which simulate llm work"}

@app.get("/health")
def get_healthcheck():
    send_log("INFO", "User check health status")
    return {"status": 200}

@app.post("/process", status_code=202)
def submit_task(message: str):
    send_log("INFO", "Starting analyse user message")

    task = analyse_user_request.delay(message)
    send_log("INFO", f"Submitted task {task.id}. Prompt: '{message}'")
    return {"task_id": task.id, "status": "ACCEPTED"}
    
@app.get("/status/{task_id}")
def get_task_status(task_id: str):
    task_result = AsyncResult(task_id, app=celery_app)
    response_status = "PENDING"
    result_data = None
    send_log("INFO", f"Checking status for task {task_id}. Current Celery state: {task_result.state}")

    if task_result.state == 'PENDING':
         response_status = "ACCEPTED"
    elif task_result.state == 'STARTED':
        response_status = "IN_PROGRESS"
    elif task_result.state == 'SUCCESS':
        response_status = "FINISHED"
        result_data = task_result.get()
    elif task_result.state == 'FAILURE':
        response_status = "FAILED"
        try:
            exc_info = task_result.info
            if isinstance(exc_info, Exception):
                 result_data = {"error": type(exc_info).__name__, "details": str(exc_info)}
            elif isinstance(exc_info, dict) and "error" in exc_info:
                 result_data = exc_info
            else:
                 result_data = {"error": "Task Failed", "details": str(exc_info) if exc_info else "No specific error details available."}
            send_log("ERROR", f"Task {task_id} failed. Result info: {result_data}")
        except Exception as e:
            send_log("ERROR", f"Error retrieving result/info for failed task {task_id}: {e}")
            result_data = {"error": "Result Retrieval Error", "details": "Could not retrieve failure details."}

    elif task_result.state == 'RETRY':
        response_status = "RETRYING"
    else:
        response_status = task_result.state

    send_log("INFO", f"Checking status for task {task_id}. Check finished")
    return {"task_id": task_id, "status": response_status, "result": result_data}