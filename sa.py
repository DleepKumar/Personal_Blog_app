from app import app, db  # make sure 'app' is your actual filename, without .py

with app.app_context():
    db.drop_all()
    db.create_all()