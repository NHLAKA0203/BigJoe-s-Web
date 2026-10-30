from app import create_app
from app.accounting import prepare_database

app = create_app()

with app.app_context():
    prepare_database()

if __name__ == '__main__':
    app.run(debug=True)
