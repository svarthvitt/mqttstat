from fastapi import FastAPI

app = FastAPI(title="mqttstat API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "backend", "name": "mqttstat"}
