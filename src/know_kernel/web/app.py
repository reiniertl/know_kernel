"""FastAPI application — serves human-facing views."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="know_kernel", version="0.1.0")


def main() -> None:
    import uvicorn

    uvicorn.run("know_kernel.web.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
