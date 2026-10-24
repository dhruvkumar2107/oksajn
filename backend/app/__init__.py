import logging
import os
from flask import Flask
from flask_cors import CORS

from .config import config
from .models import init_db
from .routes.api import api_bp


def create_app():
    app = Flask(__name__)
    
    cors_origins = config.CORS_ORIGINS
    CORS(app, origins=cors_origins, supports_credentials=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    with app.app_context():
        init_db()

    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        return {"service": "WindSight API", "version": "1.0.0", "status": "running"}

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")