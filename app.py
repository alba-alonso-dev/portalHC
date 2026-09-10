"""
Portal de Datos Ambientales Hiberus — Pre-Fase 4
Flask application entry point.

Uso:
    venv/Scripts/python.exe app.py
    -> Abre http://localhost:5000

Variables de entorno:
    FLASK_DEBUG=true    Activa el modo debug (solo desarrollo local)
    PORT=5000           Puerto de escucha (por defecto 5000)

Arquitectura:
    app.py              <- inicialización Flask + blueprints
    database/           <- conexión y migraciones SQLite
    services/           <- OCR, extracción, emisiones, lote, factores
    routes/             <- blueprints de API
    templates/          <- frontend (index.html)
"""

import logging
import os

from flask import Flask, render_template

from database.migrations import ejecutar_migraciones
from routes.configuracion import configuracion_bp
from routes.estadisticas import estadisticas_bp
from routes.exportacion import exportacion_bp
from routes.facturas import facturas_bp
from routes.factores_admin import factores_admin_bp
from routes.fuentes import fuentes_bp
from routes.recalculo import recalculo_bp
from routes.estimaciones import estimaciones_bp
from routes.dashboard import dashboard_bp
from routes.alertas import alertas_bp
from routes.ghg_report import ghg_report_bp
from routes.objetivos import objetivos_bp  # Fase 6
from routes.admin_maestros import admin_maestros_bp  # Modo admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

# Ejecutar migraciones al importar el módulo (funciona tanto con
# `python app.py` como con gunicorn/uWSGI en producción)
ejecutar_migraciones()


def create_app() -> Flask:
    """Factory de la aplicación Flask."""
    flask_app = Flask(__name__)
    flask_app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

    # Blueprints
    flask_app.register_blueprint(facturas_bp)
    flask_app.register_blueprint(exportacion_bp)
    flask_app.register_blueprint(estadisticas_bp)
    flask_app.register_blueprint(configuracion_bp)
    flask_app.register_blueprint(factores_admin_bp)
    flask_app.register_blueprint(fuentes_bp)
    flask_app.register_blueprint(recalculo_bp)
    flask_app.register_blueprint(estimaciones_bp)
    flask_app.register_blueprint(dashboard_bp)
    flask_app.register_blueprint(alertas_bp)
    flask_app.register_blueprint(ghg_report_bp)
    flask_app.register_blueprint(objetivos_bp)   # Fase 6
    flask_app.register_blueprint(admin_maestros_bp)   # Modo admin

    @flask_app.route("/")
    def index():
        return render_template("index.html")

    @flask_app.errorhandler(413)
    def too_large(e):
        from flask import jsonify
        return jsonify({"exito": False, "error": "Archivo demasiado grande (max 50 MB)"}), 413

    @flask_app.errorhandler(404)
    def not_found(e):
        from flask import jsonify
        return jsonify({"exito": False, "error": "Ruta no encontrada"}), 404

    @flask_app.errorhandler(500)
    def server_error(e):
        from flask import jsonify
        return jsonify({"exito": False, "error": "Error interno del servidor"}), 500

    return flask_app


app = create_app()


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    port  = int(os.getenv("PORT", 5000))
    print("\n" + "=" * 60)
    print("Portal de Datos Ambientales - Hiberus  (Fase 4)")
    print("=" * 60)
    print(f"URL:   http://localhost:{port}")
    print(f"BD:    facturas_hc.db")
    print(f"Debug: {debug}")
    print("  Módulos: Dashboard ESG · Alertas · Informe GHG · Estimaciones avanzadas")
    print("=" * 60 + "\n")
    app.run(debug=debug, host="0.0.0.0", port=port, use_reloader=False)
