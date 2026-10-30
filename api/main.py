from fastapi import FastAPI

app = FastAPI(title="PulseFlow Forecast API")


@app.get("/api/health")
def health():
    return {"status": "ok"}