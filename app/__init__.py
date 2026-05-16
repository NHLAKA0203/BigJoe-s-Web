from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from config import Config
from app.models import db

login_manager = LoginManager()
migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.manager import bp as manager_bp
    app.register_blueprint(manager_bp)

    from app.supplier import bp as supplier_bp
    app.register_blueprint(supplier_bp)

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    return app


@login_manager.user_loader
def load_user(user_id):
    from app.models import User
    return db.session.get(User, int(user_id))
