from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
import datetime
import uuid
import random

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")
def get_db() :
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
def group_orders(rows):
    groups = {}
    for r in rows:
        r = dict(r)
        g = groups.setdefault(r["batch_id"], {
            "batch_id": r["batch_id"], "ref": r["id"], "status": r["status"],
            "phone": r.get("phone"), "address": r.get("address"),
            "customer_name": r.get("customer_name"), "store_name": r.get("store_name"),
            "created_at": r.get("created_at"), "delivered_at": r.get("delivered_at"),
            "delivery_code": r.get("delivery_code"), "items": [], "total": 0})
        g["ref"] = min(g["ref"], r["id"])
        price = r.get("unit_price") or r["price"]
        g["items"].append({"order_id": r["id"], "name": r["product_name"],
                           "quantity": r["quantity"], "price": price})
        g["total"] += price * r["quantity"]
    return list(groups.values())


def init_db() :
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT , 
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            store_name TEXT,
            whatsapp_number TEXT
                    
                 )
""")



    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT , 
        store_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        category TEXT NOT NULL DEFAULT 'أخرى',
        FOREIGN KEY (store_id) REFERENCES users (id)         
    )
""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            confirmed_at TEXT,
            FOREIGN KEY (customer_id) REFERENCES users (id),
            FOREIGN KEY (store_id) REFERENCES users (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TEXT,
            FOREIGN KEY (order_id) REFERENCES orders (id),
            FOREIGN KEY (customer_id) REFERENCES users (id),
            FOREIGN KEY (store_id) REFERENCES users (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
                                                       )
                                                """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN delivery_available INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    for sql in (
        "ALTER TABLE orders ADD COLUMN batch_id TEXT",
        "ALTER TABLE orders ADD COLUMN unit_price REAL",
        "ALTER TABLE orders ADD COLUMN delivery_code TEXT",
        "ALTER TABLE orders ADD COLUMN code_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN created_at TEXT",
        "ALTER TABLE orders ADD COLUMN accepted_at TEXT",
        "ALTER TABLE orders ADD COLUMN delivered_at TEXT",
    ):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass

    # ترحيل الطلبات القديمة
    for r in conn.execute("SELECT id FROM orders WHERE batch_id IS NULL").fetchall():
        conn.execute("UPDATE orders SET batch_id = ? WHERE id = ?", ("old-%s" % r["id"], r["id"]))
    conn.execute("UPDATE orders SET unit_price = (SELECT price FROM products WHERE products.id = orders.product_id) WHERE unit_price IS NULL")
    for r in conn.execute("SELECT DISTINCT batch_id FROM orders WHERE delivery_code IS NULL").fetchall():
        conn.execute("UPDATE orders SET delivery_code = ? WHERE batch_id = ?",
                     ("%04d" % random.randint(0, 9999), r["batch_id"]))
    conn.commit()
    conn.close()



@app.route("/")
def index():
    if session.get("role") == "store":
        return redirect(url_for("store_dashboard"))
    if session.get("role") == "customer":
        return redirect(url_for("customer_home"))
    return render_template("landing.html")

@app.route("/register", methods=["GET", "POST"])
def register() :
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"]
        store_name = request.form.get("store_name")
        whatsapp_number = request.form.get("whatsapp_number")

        if role == "store" and not whatsapp_number:
            flash("رقم الواتساب مطلوب لأصحاب المحلات")
            return redirect(url_for("register"))
        conn = get_db()
        existing = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if existing:
            conn.close()
            if check_password_hash(existing["password"], password):
                session["user_id"] = existing["id"]
                session["role"] = existing["role"]
                session["name"] = existing["name"]
                if existing["role"] == "store":
                    return redirect(url_for("store_dashboard"))
                return redirect(url_for("customer_home"))

            flash("this email already has an account - wrong password")
            return redirect(url_for("login"))

        hashed_pw = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (name, email, password, role, store_name, whatsapp_number) VALUES(?, ?, ?, ?, ?, ?)",
            (name, email, hashed_pw, role, store_name, whatsapp_number))
        conn.commit()
        conn.close()
        flash("account created. log in now")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["name"] = user["name"]

            if user["role"] == "store" :
                return redirect(url_for("store_dashboard"))
            else:
                return redirect(url_for("customer_home"))
            
        else:
            flash("the email or password was wrong")
            return redirect(url_for("login"))
        
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/store/dashboard", methods=["GET", "POST"])
def store_dashboard():
    if session.get("role") != "store":
        return redirect(url_for("login"))
    
    conn = get_db()   # <-- لازم يجي الأول

    if request.method == "POST":
        name = request.form["product_name"]
        price = float(request.form["price"])
        quantity = int(request.form["quantity"])
        category = request.form["category"]
        conn.execute(
            "INSERT INTO products (store_id, name, price, quantity, category) VALUES (?, ?, ?, ?, ?)",
            (session["user_id"], name, price, quantity, category)
        )
        conn.commit()

    products = conn.execute(
        "SELECT * FROM products WHERE store_id = ?", (session["user_id"],)
    ).fetchall()

    avg = conn.execute(     # <-- هنا، قبل conn.close()
        "SELECT AVG(rating) as avg_rating, COUNT(*) as total FROM reviews WHERE store_id = ?",
        (session["user_id"],)
    ).fetchone()
    me = conn.execute("SELECT delivery_available FROM users WHERE id = ?",
                      (session["user_id"],)).fetchone()
    conn.close()

    return render_template("store_dashboard.html", products=products, name=session["name"],
                           avg=avg, delivery=me["delivery_available"])
@app.route("/store/delivery/toggle", methods=["POST"])
def toggle_delivery():
    if session.get("role") != "store":
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute("UPDATE users SET delivery_available = 1 - delivery_available WHERE id = ?",
                 (session["user_id"],))
    conn.commit()
    conn.close()
    return redirect(url_for("store_dashboard"))
@app.route("/store/delete/<int:product_id>")
def delete_product(product_id):
    if session.get("role") != "store":
        return redirect(url_for("login"))

    conn = get_db()
    conn.execute(
        "DELETE FROM products WHERE id = ? AND store_id = ?",
        (product_id, session["user_id"])
    )
    conn.commit()
    conn.close()
    return redirect(url_for("store_dashboard"))

@app.route("/store/orders")
def store_orders():
    if session.get("role") != "store":
        return redirect(url_for("login"))
    conn = get_db()
    rows = conn.execute("""
        SELECT orders.id, orders.batch_id, orders.quantity, orders.status, orders.phone,
               orders.address, orders.unit_price, orders.created_at, orders.delivered_at,
               products.name AS product_name, products.price,
               users.name AS customer_name
        FROM orders
        JOIN products ON orders.product_id = products.id
        JOIN users ON orders.customer_id = users.id
        WHERE orders.store_id = ?
        ORDER BY orders.id DESC
    """, (session["user_id"],)).fetchall()
    conn.close()
    return render_template("store_orders.html", orders=group_orders(rows))


@app.route("/store/order/accept/<batch_id>", methods=["POST"])
def store_accept(batch_id):
    if session.get("role") != "store":
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute(
        "UPDATE orders SET status = 'accepted', accepted_at = ? WHERE batch_id = ? AND store_id = ? AND status = 'pending'",
        (datetime.datetime.now().isoformat(timespec="seconds"), batch_id, session["user_id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("store_orders"))


@app.route("/store/order/reject/<batch_id>", methods=["POST"])
def store_reject(batch_id):
    if session.get("role") != "store":
        return redirect(url_for("login"))
    conn = get_db()
    rows = conn.execute(
        "SELECT product_id, quantity FROM orders WHERE batch_id = ? AND store_id = ? AND status IN ('pending','accepted')",
        (batch_id, session["user_id"])).fetchall()
    for r in rows:
        conn.execute("UPDATE products SET quantity = quantity + ? WHERE id = ?", (r["quantity"], r["product_id"]))
    conn.execute(
        "UPDATE orders SET status = 'rejected' WHERE batch_id = ? AND store_id = ? AND status IN ('pending','accepted')",
        (batch_id, session["user_id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("store_orders"))


@app.route("/store/order/deliver/<batch_id>", methods=["POST"])
def store_deliver(batch_id):
    if session.get("role") != "store":
        return redirect(url_for("login"))
    code = request.form.get("code", "").strip()
    conn = get_db()
    o = conn.execute(
        "SELECT delivery_code, code_attempts FROM orders WHERE batch_id = ? AND store_id = ? AND status = 'accepted' LIMIT 1",
        (batch_id, session["user_id"])).fetchone()
    if not o:
        flash("الطلب غير متاح للتسليم")
    elif o["code_attempts"] >= 5:
        flash("تم إيقاف المحاولات على الطلب ده")
    elif code != o["delivery_code"]:
        conn.execute("UPDATE orders SET code_attempts = code_attempts + 1 WHERE batch_id = ?", (batch_id,))
        conn.commit()
        flash("الكود غلط")
    else:
        conn.execute(
            "UPDATE orders SET status = 'delivered', delivered_at = ? WHERE batch_id = ? AND store_id = ?",
            (datetime.datetime.now().isoformat(timespec="seconds"), batch_id, session["user_id"]))
        conn.commit()
        flash("تم التسليم وتوثيق الريسيت ✅")
    conn.close()
    return redirect(url_for("store_orders"))



@app.route("/home")
def customer_home():
    if session.get("role") != "customer":
        return redirect(url_for("login"))
    
    
    
    conn = get_db()
    stores = conn.execute("""
    SELECT users.id, users.name, users.store_name, users.whatsapp_number,
           AVG(reviews.rating) as avg_rating, COUNT(reviews.id) as total_reviews
    FROM users
    LEFT JOIN reviews ON reviews.store_id = users.id
    WHERE users.role = 'store'
    GROUP BY users.id
""").fetchall()
    conn.close()

    return render_template("customer_home.html", stores=stores, name=session["name"])

@app.route("/store/<int:store_id>")
def view_store(store_id):
    if session.get("role") != "customer":
        return redirect(url_for("login"))

    conn = get_db()
    store = conn.execute("SELECT * FROM users WHERE id = ?", (store_id,)).fetchone()
    categories = conn.execute(
        "SELECT DISTINCT category FROM products WHERE store_id = ?", (store_id,)
    ).fetchall()
    avg = conn.execute(
        "SELECT AVG(rating) as avg_rating, COUNT(*) as total FROM reviews WHERE store_id = ?",
        (store_id,)
    ).fetchone()
    conn.close()

    return render_template("view_store.html", store=store, categories=categories, avg=avg)


@app.route("/store/<int:store_id>/category/<category>")
def view_category(store_id, category):
    if session.get("role") != "customer":
        return redirect(url_for("login"))

    conn = get_db()
    products = conn.execute(
        "SELECT * FROM products WHERE store_id = ? AND category = ?", (store_id, category)
    ).fetchall()
    conn.close()

    return render_template("view_category.html", products=products, category=category, store_id=store_id)
    
@app.route("/orders")
def my_orders():
    if session.get("role") != "customer":
        return redirect(url_for("login"))
    conn = get_db()
    rows = conn.execute("""
        SELECT orders.id, orders.batch_id, orders.quantity, orders.status, orders.unit_price,
               orders.created_at, orders.delivered_at, orders.delivery_code,
               products.name AS product_name, products.price,
               users.store_name
        FROM orders
        JOIN products ON orders.product_id = products.id
        JOIN users ON orders.store_id = users.id
        WHERE orders.customer_id = ?
        ORDER BY orders.id DESC
    """, (session["user_id"],)).fetchall()
    reviewed = {r["order_id"] for r in conn.execute(
        "SELECT order_id FROM reviews WHERE customer_id = ?", (session["user_id"],))}
    conn.close()
    return render_template("my_orders.html", orders=group_orders(rows), reviewed=reviewed)


@app.route("/receipt/<batch_id>")
def receipt(batch_id):
    uid, role = session.get("user_id"), session.get("role")
    if not uid:
        return redirect(url_for("login"))
    col = "customer_id" if role == "customer" else "store_id"
    conn = get_db()
    rows = conn.execute(f"""
        SELECT orders.id, orders.batch_id, orders.quantity, orders.status, orders.phone,
               orders.address, orders.unit_price, orders.created_at, orders.delivered_at,
               products.name AS product_name, products.price,
               c.name AS customer_name, s.store_name AS store_name
        FROM orders
        JOIN products ON orders.product_id = products.id
        JOIN users c ON orders.customer_id = c.id
        JOIN users s ON orders.store_id = s.id
        WHERE orders.batch_id = ? AND orders.{col} = ? AND orders.status IN ('delivered','confirmed')
    """, (batch_id, uid)).fetchall()
    conn.close()
    if not rows:
        flash("الريسيت غير متاح")
        return redirect(url_for("login"))
    return render_template("receipt.html", o=group_orders(rows)[0])

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    if session.get("role") != "customer":
        return redirect(url_for("login"))
    product_id = request.form["product_id"]
    quantity = int(request.form["quantity"])
    store_id = int(request.form["store_id"])
    category = request.form["category"]

    cart = session.get("cart", {})
    if cart and session.get("cart_store_id") != store_id:
        flash("لا يمكنك الطلب من أكثر من محل في نفس الوقت")
        return redirect(url_for("view_category", store_id=store_id, category=category))

    cart[product_id] = cart.get(product_id, 0) + quantity
    session["cart"] = cart
    session["cart_store_id"] = store_id
    session.modified = True
    flash("تمت الإضافة - تقدر تدخل قسم تاني أو تكمل الطلب")
    return redirect(url_for("view_category", store_id=store_id, category=category))

@app.route("/cart", methods=["GET", "POST"])
def view_cart():
    if session.get("role") != "customer":
        return redirect(url_for("login"))

    cart = session.get("cart", {})
    store_id = session.get("cart_store_id")
    if not cart:
        flash("السلة فارغة")
        return redirect(url_for("customer_home"))

    conn = get_db()

    if request.method == "POST":
        phone = request.form["phone"]
        address = request.form["address"]
        batch_id = uuid.uuid4().hex
        code = "%04d" % random.randint(0, 9999)
        created = datetime.datetime.now().isoformat(timespec="seconds")
        for product_id, qty in cart.items():
            p = conn.execute("SELECT price FROM products WHERE id = ?", (int(product_id),)).fetchone()
            conn.execute(
                "INSERT INTO orders (customer_id, store_id, product_id, quantity, phone, address, batch_id, unit_price, delivery_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session["user_id"], store_id, int(product_id), qty, phone, address, batch_id, p["price"], code, created)
            )
            conn.execute("UPDATE products SET quantity = quantity - ? WHERE id = ?", (qty, int(product_id)))
        conn.commit()
        conn.close()
        session["cart"] = {}
        flash("تم إرسال الطلب - ده كود التسليم بتاعك، اديه للمحل عند الاستلام")
        return redirect(url_for("my_orders"))

    items = []
    for product_id, qty in cart.items():
        p = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        items.append({"product": p, "quantity": qty})
    conn.close()
    return render_template("cart.html", items=items)

@app.route("/review/<int:order_id>", methods=["GET", "POST"])
def add_review(order_id):
    if session.get("role") != "customer":
        return redirect(url_for("login"))

    conn = get_db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id = ? AND customer_id = ? AND status IN ('confirmed', 'delivered')",
        (order_id, session["user_id"])
    ).fetchone()

    if not order:
        conn.close()
        flash("لا يمكنك تقييم هذا الطلب قبل التسليم")
        return redirect(url_for("my_orders"))

    if conn.execute("SELECT 1 FROM reviews WHERE order_id = ?", (order_id,)).fetchone():
        conn.close()
        flash("قيّمت المنتج ده قبل كده")
        return redirect(url_for("my_orders"))

    product = conn.execute(
        "SELECT name FROM products WHERE id = ?", (order["product_id"],)
    ).fetchone()

    if request.method == "POST":
        try:
            rating = int(request.form["rating"])
        except (KeyError, ValueError):
            rating = 0
        if rating < 1 or rating > 5:
            conn.close()
            flash("اختار من 1 إلى 5 نجوم")
            return redirect(url_for("add_review", order_id=order_id))
        comment = request.form.get("comment")
        conn.execute(
            "INSERT INTO reviews (order_id, customer_id, store_id, product_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (order_id, session["user_id"], order["store_id"], order["product_id"], rating, comment, datetime.datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        flash("تم إضافة تقييمك الموثق ⭐")
        return redirect(url_for("my_orders"))

    conn.close()
    return render_template("add_review.html", order_id=order_id, product=product)

@app.route("/store/<int:store_id>/reviews")
def store_reviews(store_id):
    conn = get_db()
    store = conn.execute("SELECT * FROM users WHERE id = ?", (store_id,)).fetchone()
    reviews = conn.execute("""
        SELECT reviews.rating, reviews.comment, reviews.created_at, users.name, products.name AS product_name
        FROM reviews
        JOIN users ON reviews.customer_id = users.id
        JOIN products ON reviews.product_id = products.id
        WHERE reviews.store_id = ?
        ORDER BY reviews.id DESC
    """, (store_id,)).fetchall()
    avg = conn.execute(
        "SELECT AVG(rating) as avg_rating, COUNT(*) as total FROM reviews WHERE store_id = ?",
        (store_id,)
    ).fetchone()
    conn.close()
    return render_template("store_reviews.html", store=store, reviews=reviews, avg=avg)

init_db()


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    app.run(debug=True)