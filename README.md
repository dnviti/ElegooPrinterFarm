# Elegoo Printer Farm

## Running with Docker

Build the image:

```bash
docker build -t elegoo-printer-farm .
```

Run the container:

```bash
docker run -p 8000:8000 elegoo-printer-farm
```

Visit `http://localhost:8000` for the API and `http://localhost:8000/docs` for interactive docs.

## Using docker compose

For development with live reloading, use docker compose:

```bash
docker compose up --build
```

This builds the `elegoo-printer-farm` image, maps the project directory into the container, and exposes the app on port 8000.
