from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nofacenocase-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///no_face_no_case.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
path = '/home/NO_FACE_NO_CASE'

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ==================== DATABASE MODELS ====================

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    stock_quantity = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(500))
    category = db.Column(db.String(100))
    times_ordered = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    quantity = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float)
    status = db.Column(db.String(50), default='pending')
    location_lat = db.Column(db.Float)
    location_lng = db.Column(db.Float)
    location_address = db.Column(db.Text)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='orders')
    product = db.relationship('Product', backref='orders')


class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    message = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])


class StockNotification(db.Model):
    __tablename__ = 'stock_notifications'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    message = db.Column(db.Text)
    is_sent = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product', backref='notifications')


@login_manager.user_loader
def load_user(user_id):
    # FIXED: Using db.session.get() instead of query.get()
    return db.session.get(User, int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


# ==================== USER ROUTES ====================

@app.route('/')
def index():
    products = Product.query.limit(6).all()
    return render_template('index.html', products=products)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        phone = request.form.get('phone', '')

        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            flash('Username or email already exists', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='scrypt')
        new_user = User(username=username, email=email, password=hashed_password, phone=phone)
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('shop'))

        flash('Invalid username or password', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/shop')
@login_required
def shop():
    products = Product.query.filter(Product.stock_quantity > 0).all()
    return render_template('shop.html', products=products)


@app.route('/order/<int:product_id>', methods=['POST'])
@login_required
def place_order(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        flash('Product not found', 'danger')
        return redirect(url_for('shop'))

    quantity = int(request.form['quantity'])
    location_lat = request.form.get('location_lat')
    location_lng = request.form.get('location_lng')
    location_address = request.form.get('location_address')

    if quantity > product.stock_quantity:
        flash('Not enough stock available', 'danger')
        return redirect(url_for('shop'))

    total_price = product.price * quantity

    order = Order(
        user_id=current_user.id,
        product_id=product_id,
        quantity=quantity,
        total_price=total_price,
        location_lat=location_lat if location_lat else None,
        location_lng=location_lng if location_lng else None,
        location_address=location_address,
        status='pending'
    )

    product.stock_quantity -= quantity
    product.times_ordered += quantity

    if product.stock_quantity < 10:
        notification = StockNotification(
            product_id=product.id,
            message=f"Low stock alert: {product.name} has only {product.stock_quantity} units left!"
        )
        db.session.add(notification)

    db.session.add(order)
    db.session.commit()

    socketio.emit('new_order', {'order_id': order.id, 'product': product.name})

    flash('Order placed successfully!', 'success')
    return redirect(url_for('order_tracking'))


@app.route('/track-order')
@login_required
def order_tracking():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.order_date.desc()).all()
    return render_template('user/order_tracking.html', orders=orders)


@app.route('/chat')
@login_required
def chat():
    admin = User.query.filter_by(is_admin=True).first()
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == admin.id)) |
        ((Message.sender_id == admin.id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()
    return render_template('user/chat.html', messages=messages, admin=admin)


# ==================== ADMIN ROUTES ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username, is_admin=True).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('admin_dashboard'))

        flash('Invalid admin credentials', 'danger')

    return render_template('admin/admin_login.html')


@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    total_products = Product.query.count()
    low_stock_products = Product.query.filter(Product.stock_quantity < 10).count()
    top_products = Product.query.order_by(Product.times_ordered.desc()).limit(5).all()
    recent_orders = Order.query.order_by(Order.order_date.desc()).limit(10).all()
    low_stock_notifications = StockNotification.query.filter_by(is_sent=False).all()

    return render_template('admin/admin_dashboard.html',
                           total_orders=total_orders,
                           pending_orders=pending_orders,
                           total_products=total_products,
                           low_stock_products=low_stock_products,
                           top_products=top_products,
                           recent_orders=recent_orders,
                           low_stock_notifications=low_stock_notifications)


@app.route('/admin/orders')
@login_required
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.order_date.desc()).all()
    return render_template('admin/admin_orders.html', orders=orders)


@app.route('/admin/update-order-status/<int:order_id>', methods=['POST'])
@login_required
@admin_required
def update_order_status(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        flash('Order not found', 'danger')
        return redirect(url_for('admin_orders'))

    new_status = request.form['status']
    order.status = new_status
    db.session.commit()

    socketio.emit('order_status_update', {'order_id': order.id, 'status': new_status})

    flash('Order status updated', 'success')
    return redirect(url_for('admin_orders'))


@app.route('/admin/catalogue')
@login_required
@admin_required
def admin_catalogue():
    products = Product.query.all()
    return render_template('admin/admin_catalogue.html', products=products)


@app.route('/admin/add-product', methods=['POST'])
@login_required
@admin_required
def add_product():
    name = request.form['name']
    description = request.form['description']
    price = float(request.form['price'])
    stock_quantity = int(request.form['stock_quantity'])
    category = request.form['category']

    product = Product(
        name=name,
        description=description,
        price=price,
        stock_quantity=stock_quantity,
        category=category
    )

    db.session.add(product)
    db.session.commit()

    flash('Product added successfully', 'success')
    return redirect(url_for('admin_catalogue'))


@app.route('/admin/edit-product/<int:product_id>', methods=['POST'])
@login_required
@admin_required
def edit_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        flash('Product not found', 'danger')
        return redirect(url_for('admin_catalogue'))

    product.name = request.form['name']
    product.description = request.form['description']
    product.price = float(request.form['price'])
    product.stock_quantity = int(request.form['stock_quantity'])
    product.category = request.form['category']

    db.session.commit()
    flash('Product updated successfully', 'success')
    return redirect(url_for('admin_catalogue'))


@app.route('/admin/delete-product/<int:product_id>')
@login_required
@admin_required
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if product:
        db.session.delete(product)
        db.session.commit()
        flash('Product deleted', 'success')
    else:
        flash('Product not found', 'danger')
    return redirect(url_for('admin_catalogue'))


@app.route('/admin/chat')
@login_required
@admin_required
def admin_chat():
    users = User.query.filter_by(is_admin=False).all()
    return render_template('admin/admin_chat.html', users=users)


@app.route('/admin/get-messages/<int:user_id>')
@login_required
@admin_required
def get_messages(user_id):
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()

    return jsonify([{
        'sender_id': m.sender_id,
        'message': m.message,
        'timestamp': m.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    } for m in messages])


@app.route('/admin/clear-notification/<int:notification_id>')
@login_required
@admin_required
def clear_notification(notification_id):
    notification = db.session.get(StockNotification, notification_id)
    if notification:
        notification.is_sent = True
        db.session.commit()
    return jsonify({'success': True})


# ==================== SOCKETIO EVENTS ====================

@socketio.on('send_message')
def handle_send_message(data):
    message = Message(
        sender_id=data['sender_id'],
        receiver_id=data['receiver_id'],
        message=data['message']
    )
    db.session.add(message)
    db.session.commit()

    emit('receive_message', {
        'sender_id': data['sender_id'],
        'message': data['message'],
        'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    }, room=str(data['receiver_id']))


@socketio.on('join')
def handle_join(data):
    from flask_socketio import join_room
    join_room(str(data['user_id']))


# ==================== DATABASE INITIALIZATION ====================

def init_db():
    """Initialize database with admin user and sample products"""
    db.create_all()

    # Create admin user if not exists
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        hashed_password = generate_password_hash('admin123', method='scrypt')
        admin = User(
            username='admin',
            email='admin@nofacenocase.com',
            password=hashed_password,
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()
        print("✓ Admin user created: username='admin', password='admin123'")

    # Add sample products if none exist
    if Product.query.count() == 0:
        sample_products = [
            Product(name='Pacific Storm Energy Drink',
                    description='High-energy drink for extreme focus. Perfect for long gaming sessions or late night work.',
                    price=3.99, stock_quantity=50, category='Beverages'),
            Product(name='Pacific Storm Hoodie',
                    description='Comfortable hoodie with storm design. 100% cotton, available in multiple sizes.',
                    price=45.99, stock_quantity=30, category='Apparel'),
            Product(name='Pacific Storm Cap',
                    description='Limited edition baseball cap with embroidered logo. Adjustable strap, one size fits most.',
                    price=19.99, stock_quantity=45, category='Accessories'),
            Product(name='Pacific Storm Sticker Pack',
                    description='Set of 10 unique storm-themed stickers. High quality vinyl, waterproof.', price=9.99,
                    stock_quantity=100, category='Merchandise'),
            Product(name='Pacific Storm T-Shirt',
                    description='Premium quality t-shirt with front print. Available in S, M, L, XL.', price=29.99,
                    stock_quantity=40, category='Apparel'),
            Product(name='Pacific Storm Water Bottle',
                    description='Stainless steel water bottle. Keeps drinks cold for 24 hours.', price=24.99,
                    stock_quantity=35, category='Accessories')
        ]
        for product in sample_products:
            db.session.add(product)
        db.session.commit()
        print("✓ Sample products added successfully!")

    print("\n" + "=" * 50)
    print("DATABASE INITIALIZATION COMPLETE!")
    print("=" * 50)
    print("Admin Login: admin / admin123")
    print("Website URL: http://127.0.0.1:5000")
    print("=" * 50 + "\n")


if __name__ == '__main__':
    with app.app_context():
        init_db()
    socketio.run(app, debug=True, port=5003)