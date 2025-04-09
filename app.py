from flask import Flask, render_template, redirect, url_for, request, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os

# --- Flask Setup ---
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- DB Setup ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    photo = db.Column(db.String(100), nullable=True)
    wallpaper = db.Column(db.String(100), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def friends_count(self):
        sent = FriendRequest.query.filter_by(sender_id=self.id, status='accepted').count()
        received = FriendRequest.query.filter_by(receiver_id=self.id, status='accepted').count()
        return sent + received

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='posts')

class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- Context Processor ---
@app.context_processor
def inject_notifications():
    notifications = []
    if 'user_id' in session:
        notifications = Notification.query.filter_by(user_id=session['user_id']) \
                                          .order_by(Notification.timestamp.desc()) \
                                          .limit(5).all()
    return dict(notifications=notifications)

# --- Routes ---
@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    posts = Post.query.order_by(Post.timestamp.desc()).all()
    return render_template("home.html", user=user, posts=posts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
            return redirect(url_for('register'))
        user = User(username=username, password=password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful. Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            flash('Login successful.')
            return redirect(url_for('home'))
        flash('Invalid credentials.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Logged out.')
    return redirect(url_for('login'))

@app.route('/create', methods=['GET', 'POST'])
def create():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        post = Post(title=title, content=content, user_id=session['user_id'])
        db.session.add(post)
        db.session.commit()
        return redirect(url_for('home'))
    return render_template('create.html')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    post = Post.query.get_or_404(id)
    if session.get('user_id') != post.user_id:
        return redirect(url_for('home'))
    if request.method == 'POST':
        post.title = request.form['title']
        post.content = request.form['content']
        db.session.commit()
        return redirect(url_for('home'))
    return render_template('edit.html', post=post)

@app.route('/delete/<int:id>')
def delete(id):
    post = Post.query.get_or_404(id)
    if session.get('user_id') == post.user_id:
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/user/<username>')
def user_posts(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(user_id=user.id).all()
    return render_template('user_posts.html', posts=posts, user=user)

@app.route('/send_request/<int:receiver_id>', methods=['POST'])
def send_request(receiver_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    existing_request = FriendRequest.query.filter_by(sender_id=session['user_id'], receiver_id=receiver_id).first()
    if not existing_request:
        new_request = FriendRequest(sender_id=session['user_id'], receiver_id=receiver_id)
        db.session.add(new_request)
        note = Notification(user_id=receiver_id, message=f"{User.query.get(session['user_id']).username} sent you a friend request!")
        db.session.add(note)
        db.session.commit()
        flash('Friend request sent.')
    else:
        flash('Friend request already sent.')
    return redirect(url_for('search_users'))

@app.route('/accept_request/<int:request_id>')
def accept_request(request_id):
    fr = FriendRequest.query.get_or_404(request_id)
    if fr.receiver_id == session.get('user_id'):
        fr.status = 'accepted'
        note = Notification(user_id=fr.sender_id, message=f"{User.query.get(fr.receiver_id).username} accepted your friend request!")
        db.session.add(note)
        db.session.commit()
        flash('Friend request accepted.')
    return redirect(url_for('friend_requests'))

@app.route('/reject_request/<int:request_id>')
def reject_request(request_id):
    fr = FriendRequest.query.get_or_404(request_id)
    if fr.receiver_id == session.get('user_id'):
        fr.status = 'rejected'
        note = Notification(user_id=fr.sender_id, message=f"{User.query.get(fr.receiver_id).username} rejected your friend request.")
        db.session.add(note)
        db.session.commit()
        flash('Friend request rejected.')
    return redirect(url_for('friend_requests'))

@app.route('/friends')
def friends():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    sent = FriendRequest.query.filter_by(sender_id=user_id, status='accepted').all()
    received = FriendRequest.query.filter_by(receiver_id=user_id, status='accepted').all()
    friend_ids = [f.receiver_id for f in sent] + [f.sender_id for f in received]
    friends = User.query.filter(User.id.in_(friend_ids)).all()
    return render_template('friends.html', friends=friends)

@app.route('/friend_requests')
def friend_requests():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    requests = FriendRequest.query.filter_by(receiver_id=session['user_id'], status='pending').all()
    return render_template('friend_requests.html', requests=requests)

@app.route('/search', methods=['GET', 'POST'])
def search_users():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    results = []
    if request.method == 'POST':
        query = request.form['query']
        user_id = session['user_id']
        excluded_ids = [user_id]
        sent = FriendRequest.query.filter_by(sender_id=user_id).all()
        received = FriendRequest.query.filter_by(receiver_id=user_id).all()
        excluded_ids += [r.receiver_id for r in sent] + [r.sender_id for r in received]
        results = User.query.filter(User.username.contains(query), ~User.id.in_(excluded_ids)).all()
    return render_template('search.html', results=results)

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    posts_count = Post.query.filter_by(user_id=user.id).count()
    friends_count = user.friends_count
    latest_notifications = Notification.query.filter_by(user_id=user.id).order_by(Notification.timestamp.desc()).limit(5).all()
    return render_template('profile.html', user=user, posts_count=posts_count, friends_count=friends_count, latest_notifications=latest_notifications)

@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        user.bio = request.form['bio']
        photo = request.files.get('photo')
        if photo and photo.filename != "":
            photo_filename = secure_filename(photo.filename)
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename))
            user.photo = photo_filename
        wallpaper = request.files.get('wallpaper')
        if wallpaper and wallpaper.filename != "":
            wallpaper_filename = secure_filename(wallpaper.filename)
            wallpaper.save(os.path.join(app.config['UPLOAD_FOLDER'], wallpaper_filename))
            user.wallpaper = wallpaper_filename
        db.session.commit()
        flash('Profile updated!')
        return redirect(url_for('profile'))
    return render_template('edit_profile.html', user=user)

# --- Run App ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
