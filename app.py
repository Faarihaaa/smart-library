import sqlite3
import requests
from flask import Flask, redirect, render_template, request, session

app = Flask(__name__)
app.secret_key = "supersecretkey"


def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            genre TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            book_id INTEGER NOT NULL,
            rating INTEGER
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM books")
    if cursor.fetchone()[0] == 0:
        sample_books = [
            ("The Alchemist", "Paulo Coelho", "Fiction"),
            ("Atomic Habits", "James Clear", "Self-Help"),
            ("1984", "George Orwell", "Fiction"),
            ("Sapiens", "Yuval Noah Harari", "History"),
            ("The Power of Habit", "Charles Duhigg", "Self-Help"),
            ("Brief Answers to the Big Questions", "Stephen Hawking", "Science"),
        ]
        cursor.executemany(
            "INSERT INTO books (title, author, genre) VALUES (?, ?, ?)",
            sample_books,
        )
    conn.commit()
    conn.close()


@app.route("/")
def home():
    if "user" in session:
        return render_template(
            "index.html", logged_in=True, user=session["user"]
        )
    return render_template("index.html", logged_in=False)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (email, password) VALUES (?, ?)",
                (email, password),
            )
            conn.commit()
            conn.close()
            return redirect("/login")
        except sqlite3.IntegrityError:
            conn.close()
            return render_template(
                "signup.html", error="Email already registered"
            )
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE email=? AND password=?", (email, password)
        )
        user = cursor.fetchone()
        conn.close()

        if user:
            session["user"] = email
            return redirect("/")
        else:
            return render_template(
                "login.html", error="Invalid email or password"
            )
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


@app.route("/books")
def books():
    if "user" not in session:
        return redirect("/login")

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM books")
    all_books = cursor.fetchall()
    conn.close()

    rated = request.args.get("rated")
    return render_template(
        "books.html", books=all_books, user=session["user"], rated=rated
    )


@app.route("/rate/<int:book_id>", methods=["POST"])
def rate(book_id):
    if "user" not in session:
        return redirect("/login")

    rating = request.form["rating"]
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO history (user_email, book_id, rating) VALUES (?, ?, ?)",
        (session["user"], book_id, rating),
    )
    conn.commit()
    conn.close()

    return redirect("/books?rated=1")


@app.route("/recommendations")
def recommendations():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT DISTINCT books.genre, books.author
        FROM history
        JOIN books ON history.book_id = books.id
        WHERE history.user_email = ? AND history.rating >= 4
    """,
        (user_email,),
    )
    liked = cursor.fetchall()

    cursor.execute(
        "SELECT book_id FROM history WHERE user_email = ?", (user_email,)
    )
    rated_ids = [row[0] for row in cursor.fetchall()]

    recommended = []
    if liked:
        liked_genres = set(g for g, a in liked)
        liked_authors = set(a for g, a in liked)

        cursor.execute("SELECT * FROM books")
        all_books = cursor.fetchall()

        for book in all_books:
            book_id, title, author, genre = book
            if book_id in rated_ids:
                continue
            if genre in liked_genres or author in liked_authors:
                recommended.append(book)

    conn.close()

    return render_template(
        "recommendations.html", books=recommended, user=user_email
    )


def check_gutenberg(title):
    try:
        response = requests.get(
            "https://gutendex.com/books",
            params={"search": title},
            timeout=5,
        )
        data = response.json()
        if data.get("results"):
            book = data["results"][0]
            formats = book.get("formats", {})
            return formats.get("application/epub+zip") or formats.get(
                "text/plain; charset=utf-8"
            )
    except Exception:
        pass
    return None


@app.route("/search")
def search():
    if "user" not in session:
        return redirect("/login")

    query = request.args.get("q", "").strip()
    results = []

    if query:
        try:
            # Open Library API avoids Google Books API Quota Limits
            response = requests.get(
                "https://openlibrary.org/search.json",
                params={"q": query, "limit": 5},
                timeout=5,
            )
            data = response.json()
            docs = data.get("docs", [])

            for doc in docs:
                title = doc.get("title", "Unknown Title")
                authors = ", ".join(doc.get("author_name", ["Unknown Author"]))

                # Fetch thumbnail image
                cover_id = doc.get("cover_i")
                thumbnail = (
                    f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
                    if cover_id
                    else ""
                )

                key = doc.get("key", "")
                preview_link = (
                    f"https://openlibrary.org{key}" if key else "#"
                )

                results.append({
                    "title": title,
                    "authors": authors,
                    "thumbnail": thumbnail,
                    "description": (
                        f"First published in"
                        f" {doc.get('first_publish_year', 'N/A')}."
                    ),
                    "preview_link": preview_link,
                    "download_link": None,
                })
        except Exception as e:
            print("SEARCH ERROR:", e)

    return render_template(
        "search.html", results=results, query=query, user=session["user"]
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)