import sqlite3
from flask import Flask, render_template, request, redirect, session, url_for, g

app = Flask(__name__)
app.secret_key = "senha_super_secreta_troque_depois"

DATABASE = "community.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def add_column_if_not_exists(cursor, table_name, column_name, definition):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db():
    db = sqlite3.connect(DATABASE)
    cursor = db.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        profile_photo TEXT DEFAULT ''
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS communities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        owner_id INTEGER,
        is_private INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS community_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        community_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        UNIQUE(community_id, user_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        community_id INTEGER NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        image_url TEXT DEFAULT '',
        video_url TEXT DEFAULT '',
        user_id INTEGER NOT NULL,
        community_id INTEGER NOT NULL,
        channel_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        UNIQUE(user_id, post_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS profile_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        text TEXT,
        image_url TEXT DEFAULT '',
        video_url TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS profile_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        profile_post_id INTEGER NOT NULL,
        UNIQUE(user_id, profile_post_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS friend_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending'
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS friends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        friend_id INTEGER NOT NULL,
        UNIQUE(user_id, friend_id)
    )
    """)

    add_column_if_not_exists(cursor, "users", "bio", "TEXT DEFAULT ''")
    add_column_if_not_exists(cursor, "users", "is_private", "INTEGER DEFAULT 0")
    add_column_if_not_exists(cursor, "posts", "channel_id", "INTEGER")

    db.commit()
    db.close()


def ensure_default_channels(db, community_id):
    existing = db.execute(
        "SELECT * FROM channels WHERE community_id = ?",
        (community_id,)
    ).fetchall()

    if not existing:
        for name in ["general", "chat", "media"]:
            db.execute(
                "INSERT INTO channels (name, community_id) VALUES (?, ?)",
                (name, community_id)
            )
        db.commit()


def are_friends(db, user_a, user_b):
    if user_a == user_b:
        return True

    friendship = db.execute("""
        SELECT * FROM friends
        WHERE (user_id = ? AND friend_id = ?)
           OR (user_id = ? AND friend_id = ?)
    """, (user_a, user_b, user_b, user_a)).fetchone()

    return friendship is not None


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        profile_photo = request.form.get("profile_photo", "").strip()

        if not username or not email or not password:
            return "Please fill in all fields"

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (username, email, password, profile_photo) VALUES (?, ?, ?, ?)",
                (username, email, password, profile_photo)
            )
            db.commit()
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            return "Username or email already exists"

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ? AND password = ?",
            (email, password)
        ).fetchone()

        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("home"))
        else:
            error = "Email or password is incorrect"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/communities", methods=["GET", "POST"])
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        is_private = 1 if request.form.get("is_private") == "on" else 0

        if name:
            try:
                cursor = db.execute(
                    "INSERT INTO communities (name, description, owner_id, is_private) VALUES (?, ?, ?, ?)",
                    (name, description, session["user_id"], is_private)
                )
                community_id = cursor.lastrowid

                db.execute(
                    "INSERT OR IGNORE INTO community_members (community_id, user_id) VALUES (?, ?)",
                    (community_id, session["user_id"])
                )

                db.commit()
                ensure_default_channels(db, community_id)

            except sqlite3.IntegrityError:
                return "A group with this name already exists"

    query = request.args.get("q", "").strip()

    if query:
        communities = db.execute(
            "SELECT * FROM communities WHERE name LIKE ? ORDER BY id DESC",
            (f"%{query}%",)
        ).fetchall()
    else:
        communities = db.execute(
            "SELECT * FROM communities ORDER BY id DESC"
        ).fetchall()

    return render_template("home.html", communities=communities, query=query)


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_profile":
            username = request.form.get("username", "").strip()
            profile_photo = request.form.get("profile_photo", "").strip()
            bio = request.form.get("bio", "").strip()
            is_private = 1 if request.form.get("is_private") == "on" else 0

            db.execute("""
                UPDATE users
                SET username = ?, profile_photo = ?, bio = ?, is_private = ?
                WHERE id = ?
            """, (username, profile_photo, bio, is_private, session["user_id"]))
            db.commit()
            session["username"] = username

        return redirect(url_for("profile"))

    user = db.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    friends = db.execute("""
        SELECT users.*
        FROM friends
        JOIN users ON friends.friend_id = users.id
        WHERE friends.user_id = ?
        ORDER BY users.username
    """, (session["user_id"],)).fetchall()

    posts = db.execute("""
        SELECT profile_posts.*,
               (SELECT COUNT(*) FROM profile_likes WHERE profile_likes.profile_post_id = profile_posts.id) AS like_count
        FROM profile_posts
        WHERE profile_posts.user_id = ?
        ORDER BY profile_posts.id DESC
    """, (session["user_id"],)).fetchall()

    liked_profile_post_ids = [
        row["profile_post_id"] for row in db.execute(
            "SELECT profile_post_id FROM profile_likes WHERE user_id = ?",
            (session["user_id"],)
        ).fetchall()
    ]

    received_requests = db.execute("""
        SELECT friend_requests.*, users.username
        FROM friend_requests
        JOIN users ON users.id = friend_requests.sender_id
        WHERE friend_requests.receiver_id = ? AND friend_requests.status = 'pending'
        ORDER BY friend_requests.id DESC
    """, (session["user_id"],)).fetchall()

    return render_template(
        "profile.html",
        user=user,
        friends=friends,
        posts=posts,
        liked_profile_post_ids=liked_profile_post_ids,
        own_profile=True,
        can_view_posts=True,
        received_requests=received_requests,
        is_friend=False,
        request_sent=False
    )


@app.route("/community/<int:community_id>")
def community_redirect(community_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    ensure_default_channels(db, community_id)

    first_channel = db.execute(
        "SELECT * FROM channels WHERE community_id = ? ORDER BY id ASC",
        (community_id,)
    ).fetchone()

    if not first_channel:
        return "No channels found"

    return redirect(url_for("channel_view", community_id=community_id, channel_id=first_channel["id"]))


@app.route("/community/<int:community_id>/channel/<int:channel_id>", methods=["GET", "POST"])
def channel_view(community_id, channel_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()

    community = db.execute(
        "SELECT * FROM communities WHERE id = ?",
        (community_id,)
    ).fetchone()

    if not community:
        return "Community not found"

    ensure_default_channels(db, community_id)

    is_member = db.execute(
        "SELECT * FROM community_members WHERE community_id = ? AND user_id = ?",
        (community_id, session["user_id"])
    ).fetchone()

    if community["is_private"] == 1 and not is_member and community["owner_id"] != session["user_id"]:
        return "This community is private"

    channel = db.execute(
        "SELECT * FROM channels WHERE id = ? AND community_id = ?",
        (channel_id, community_id)
    ).fetchone()

    if not channel:
        return "Channel not found"

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create_post":
            text = request.form.get("text", "").strip()
            image_url = request.form.get("image_url", "").strip()
            video_url = request.form.get("video_url", "").strip()

            if text or image_url or video_url:
                db.execute("""
                    INSERT INTO posts (text, image_url, video_url, user_id, community_id, channel_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (text, image_url, video_url, session["user_id"], community_id, channel_id))
                db.commit()

            return redirect(url_for("channel_view", community_id=community_id, channel_id=channel_id))

    channels = db.execute(
        "SELECT * FROM channels WHERE community_id = ? ORDER BY id ASC",
        (community_id,)
    ).fetchall()

    communities = db.execute(
        "SELECT * FROM communities ORDER BY id DESC"
    ).fetchall()

    members = db.execute("""
        SELECT users.username
        FROM community_members
        JOIN users ON community_members.user_id = users.id
        WHERE community_members.community_id = ?
    """, (community_id,)).fetchall()

    posts = db.execute("""
        SELECT posts.*, users.username, users.profile_photo,
               (SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) AS like_count
        FROM posts
        JOIN users ON posts.user_id = users.id
        WHERE posts.community_id = ? AND posts.channel_id = ?
        ORDER BY posts.id DESC
    """, (community_id, channel_id)).fetchall()

    liked_post_ids = [
        row["post_id"] for row in db.execute(
            "SELECT post_id FROM likes WHERE user_id = ?",
            (session["user_id"],)
        ).fetchall()
    ]

    return render_template(
        "community.html",
        community=community,
        communities=communities,
        channels=channels,
        current_channel=channel,
        members=members,
        posts=posts,
        liked_post_ids=liked_post_ids
    )


@app.route("/create_channel/<int:community_id>", methods=["POST"])
def create_channel(community_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    community = db.execute("SELECT * FROM communities WHERE id = ?", (community_id,)).fetchone()

    if not community:
        return "Community not found"

    if community["owner_id"] != session["user_id"]:
        return "Only the owner can create channels"

    channel_name = request.form.get("channel_name", "").strip()

    if channel_name:
        db.execute(
            "INSERT INTO channels (name, community_id) VALUES (?, ?)",
            (channel_name, community_id)
        )
        db.commit()

    return redirect(url_for("community_redirect", community_id=community_id))


@app.route("/edit_channel/<int:channel_id>", methods=["POST"])
def edit_channel(channel_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    channel = db.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()

    if not channel:
        return "Channel not found"

    community = db.execute("SELECT * FROM communities WHERE id = ?", (channel["community_id"],)).fetchone()

    if community["owner_id"] != session["user_id"]:
        return "Only the owner can edit channels"

    new_channel_name = request.form.get("new_channel_name", "").strip()

    if new_channel_name:
        db.execute("UPDATE channels SET name = ? WHERE id = ?", (new_channel_name, channel_id))
        db.commit()

    return redirect(url_for("channel_view", community_id=community["id"], channel_id=channel_id))


@app.route("/delete_channel/<int:channel_id>", methods=["POST"])
def delete_channel(channel_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    channel = db.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()

    if not channel:
        return "Channel not found"

    community = db.execute("SELECT * FROM communities WHERE id = ?", (channel["community_id"],)).fetchone()

    if community["owner_id"] != session["user_id"]:
        return "Only the owner can delete channels"

    count_channels = db.execute(
        "SELECT COUNT(*) AS total FROM channels WHERE community_id = ?",
        (community["id"],)
    ).fetchone()["total"]

    if count_channels <= 1:
        return "A group must have at least one channel"

    db.execute("DELETE FROM likes WHERE post_id IN (SELECT id FROM posts WHERE channel_id = ?)", (channel_id,))
    db.execute("DELETE FROM posts WHERE channel_id = ?", (channel_id,))
    db.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    db.commit()

    return redirect(url_for("community_redirect", community_id=community["id"]))


@app.route("/edit_post/<int:post_id>", methods=["POST"])
def edit_post(post_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    post = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()

    if not post:
        return "Post not found"

    if post["user_id"] != session["user_id"]:
        return "You cannot edit this message"

    new_text = request.form.get("new_text", "").strip()
    new_image_url = request.form.get("new_image_url", "").strip()
    new_video_url = request.form.get("new_video_url", "").strip()

    db.execute("""
        UPDATE posts
        SET text = ?, image_url = ?, video_url = ?
        WHERE id = ?
    """, (new_text, new_image_url, new_video_url, post_id))
    db.commit()

    return redirect(url_for("channel_view", community_id=post["community_id"], channel_id=post["channel_id"]))


@app.route("/delete_post/<int:post_id>", methods=["POST"])
def delete_post(post_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    post = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()

    if not post:
        return "Post not found"

    if post["user_id"] != session["user_id"] and session["user_id"] != db.execute(
        "SELECT owner_id FROM communities WHERE id = ?",
        (post["community_id"],)
    ).fetchone()["owner_id"]:
        return "You cannot delete this message"

    community_id = post["community_id"]
    channel_id = post["channel_id"]

    db.execute("DELETE FROM likes WHERE post_id = ?", (post_id,))
    db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    db.commit()

    return redirect(url_for("channel_view", community_id=community_id, channel_id=channel_id))


@app.route("/edit_community/<int:community_id>", methods=["POST"])
def edit_community(community_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    community = db.execute("SELECT * FROM communities WHERE id = ?", (community_id,)).fetchone()

    if not community:
        return "Community not found"

    if community["owner_id"] != session["user_id"]:
        return "Only the owner can edit the group"

    new_name = request.form.get("new_name", "").strip()
    new_description = request.form.get("new_description", "").strip()

    if new_name:
        db.execute("""
            UPDATE communities
            SET name = ?, description = ?
            WHERE id = ?
        """, (new_name, new_description, community_id))
        db.commit()

    return redirect(url_for("community_redirect", community_id=community_id))


@app.route("/delete_community/<int:community_id>", methods=["POST"])
def delete_community(community_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    community = db.execute("SELECT * FROM communities WHERE id = ?", (community_id,)).fetchone()

    if not community:
        return "Community not found"

    if community["owner_id"] != session["user_id"]:
        return "Only the owner can delete the group"

    channel_ids = db.execute(
        "SELECT id FROM channels WHERE community_id = ?",
        (community_id,)
    ).fetchall()

    for row in channel_ids:
        db.execute("DELETE FROM likes WHERE post_id IN (SELECT id FROM posts WHERE channel_id = ?)", (row["id"],))
        db.execute("DELETE FROM posts WHERE channel_id = ?", (row["id"],))

    db.execute("DELETE FROM channels WHERE community_id = ?", (community_id,))
    db.execute("DELETE FROM community_members WHERE community_id = ?", (community_id,))
    db.execute("DELETE FROM communities WHERE id = ?", (community_id,))
    db.commit()

    return redirect(url_for("home"))


@app.route("/like_post/<int:post_id>", methods=["POST"])
def like_post(post_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()

    existing = db.execute(
        "SELECT * FROM likes WHERE user_id = ? AND post_id = ?",
        (session["user_id"], post_id)
    ).fetchone()

    if existing:
        db.execute(
            "DELETE FROM likes WHERE user_id = ? AND post_id = ?",
            (session["user_id"], post_id)
        )
    else:
        db.execute(
            "INSERT INTO likes (user_id, post_id) VALUES (?, ?)",
            (session["user_id"], post_id)
        )

    db.commit()
    next_url = request.form.get("next_url")

    if next_url:
        return redirect(next_url)

    return redirect(url_for("home"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)