"""``python -m agplat`` / ``agplat`` starts the REST API.

The API is the interface; this module is a convenience for local development,
not a second user surface.
"""

import uvicorn


def main() -> None:
    uvicorn.run(
        "agplat.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
