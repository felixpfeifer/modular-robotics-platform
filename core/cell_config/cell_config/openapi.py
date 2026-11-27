"""OpenAPI description and interactive documentation for the HTTP API."""

EXAMPLE = {
    "version": 1,
    "name": "Example cell",
    "robots": [
        {
            "id": "leader",
            "name": "Leader",
            "role": "leader",
            "driver": "robot_so101",
            "namespace": "/leader",
            "connection": {"type": "simulated"},
        }
    ],
    "cameras": [],
    "control_links": [],
}


def response(description):
    return {"description": description}


OPENAPI = {
    "openapi": "3.0.3",
    "info": {
        "title": "Cell configuration and deployment API",
        "version": "1.0.0",
        "description": "Configure a cell and operate its Docker Compose project. Deployment can start physical hardware.",
    },
    "paths": {
        "/health": {
            "get": {
                "summary": "Check HTTP service health",
                "responses": {"200": response("Running")},
            }
        },
        "/api/v1/cell": {
            "get": {
                "summary": "Get the saved cell",
                "responses": {
                    "200": response("Cell and ETag"),
                    "404": response("No cell configured"),
                },
            },
            "put": {
                "summary": "Replace the cell configuration",
                "parameters": [
                    {
                        "name": "If-Match",
                        "in": "header",
                        "schema": {"type": "string"},
                        "description": "ETag from GET to prevent overwriting newer changes",
                    },
                    {
                        "name": "If-None-Match",
                        "in": "header",
                        "schema": {"type": "string"},
                        "description": "Use * to create only if absent",
                    },
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"type": "object"},
                            "example": EXAMPLE,
                        }
                    },
                },
                "responses": {
                    "200": response("Saved cell and ETag"),
                    "400": response("Invalid configuration"),
                    "412": response("Precondition failed"),
                },
            },
        },
        "/api/v1/deployment/plan": {
            "get": {
                "summary": "Render the Compose plan",
                "responses": {
                    "200": response("Compose plan and configuration ETag"),
                    "404": response("No cell configured"),
                    "422": response("Cell cannot be deployed"),
                },
            }
        },
        "/api/v1/deployment/up": {
            "post": {
                "summary": "Start or reconcile the cell containers",
                "description": "Uses the saved configuration snapshot. Starts hardware drivers and removes orphaned containers in this project.",
                "parameters": [
                    {
                        "name": "If-Match",
                        "in": "header",
                        "schema": {"type": "string"},
                        "description": "Optional ETag of the plan you reviewed",
                    }
                ],
                "responses": {
                    "200": response("Compose command completed"),
                    "404": response("No cell configured"),
                    "412": response("Configuration changed"),
                    "422": response("Cell cannot be deployed"),
                    "502": response("Compose failed"),
                    "504": response("Compose timed out"),
                },
            }
        },
        "/api/v1/deployment/down": {
            "post": {
                "summary": "Stop and remove this project’s containers",
                "responses": {
                    "200": response("Compose command completed"),
                    "502": response("Compose failed"),
                    "504": response("Compose timed out"),
                },
            }
        },
        "/api/v1/deployment/status": {
            "get": {
                "summary": "Get Compose container status",
                "responses": {
                    "200": response("Compose output"),
                    "502": response("Compose failed"),
                    "504": response("Compose timed out"),
                },
            }
        },
    },
}

SWAGGER_HTML = """<!doctype html><html><head><title>Cell API</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url: '/openapi.json', dom_id: '#swagger-ui'});</script></body></html>"""
