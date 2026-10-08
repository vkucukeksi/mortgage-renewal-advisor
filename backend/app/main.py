from fastapi import FastAPI

app = FastAPI(title="Mortgage Renewal Advisor")


@app.get("/")
def root():
    return {
        "message": "Mortgage Renewal Advisor API is running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }