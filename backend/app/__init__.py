import logging
import os
from threading import Thread
from flask import Flask
from flask_cors import CORS

from .config import config
from .models import init_db, get_evaluation_count
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
        try:
            count = get_evaluation_count("2026-01-01", "2026-02-01")
            if count == 0:
                def _seed_live():
                    try:
                        from .services.data_processor import ingest_and_evaluate_period
                        app.logger.info("Starting live Elexon seed for 2026-01-01 to 2026-02-01 (FUELHH/WINDFOR)...")
                        stats = ingest_and_evaluate_period("2026-01-01", "2026-02-01")
                        app.logger.info(f"Live Elexon seed completed: {stats}")
                    except Exception as e:
                        app.logger.warning(f"Live Elexon seed failed: {e}")

                thread = Thread(target=_seed_live, daemon=True)
                thread.start()
                app.logger.info("Live Elexon seeding started in background")
        except Exception as e:
            app.logger.warning(f"Live seed check skipped: {e}")

    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        return {"service": "WindSight API", "version": "1.0.0", "status": "running"}

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")