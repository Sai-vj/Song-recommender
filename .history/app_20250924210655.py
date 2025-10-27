import os
import datetime
from flask import Flask, render_template, request, redirect, url_for, session
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# --- Load env ---
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback_key")

# --- Database setup ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///history.db'
db = SQLAlchemy(app)

class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mood = db.Column(db.String(50))
    playlist_name = db.Column(db.String(200))
    playlist_url = db.Column(db.String(300))
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

with app.app_context():
    db.create_all()

# --- Spotify Auth ---
sp_oauth = SpotifyOAuth(
    client_id=os.getenv("SPOTIPY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:5000/callback"),
    scope="user-library-read user-top-read playlist-read-private"
)

# --- Helper: Ensure token valid ---
def ensure_token():
    token_info = session.get("token_info")
    if not token_info:
        return None
    if sp_oauth.is_token_expired(token_info):
        try:
            refreshed = sp_oauth.refresh_access_token(token_info.get("refresh_token"))
            session["token_info"] = refreshed
            token_info = refreshed
        except Exception:
            return None
    return token_info


# --- Routes ---
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login")
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    error = request.args.get("error")
    if error:
        return f"Authorization failed: {error}", 400
    if not code:
        return "No code provided", 400
    try:
        token_info = sp_oauth.get_access_token(code)
    except Exception as e:
        return f"Token exchange failed: {e}", 500
    session["token_info"] = token_info
    return redirect(url_for("recommend"))

@app.route("/recommend", methods=["GET", "POST"])
def recommend():
    token_info = ensure_token()
    if not token_info:
        return redirect(url_for("login"))

    sp = Spotify(auth=token_info["access_token"])

    playlists = []
    if request.method == "POST":
        mood = (request.form.get("mood", "") or "").strip().lower()
        if not mood or len(mood) > 100:
            return "Invalid mood input", 400

        try:
            results = sp.search(q=mood, type="playlist", limit=5)
        except Exception as e:
            return f"Spotify search failed: {e}", 502

        entries = []
        for p in results.get("playlists", {}).get("items", []):
            playlists.append({
                "name": p.get("name"),
                "url": p.get("external_urls", {}).get("spotify")
            })
            entries.append(SearchHistory(
                mood=mood,
                playlist_name=p.get("name"),
                playlist_url=p.get("external_urls", {}).get("spotify")
            ))
        if entries:
            db.session.add_all(entries)
            db.session.commit()

        return render_template("result.html", mood=mood.capitalize(), playlists=playlists)

    return render_template("recommend.html")

@app.route("/history")
def history():
    records = SearchHistory.query.order_by(SearchHistory.timestamp.desc()).all()
    return render_template("history.html", records=records)
import datetime

@app.context_processor
def inject_now():
    return {'now': datetime.datetime.utcnow}



if __name__ == "__main__":
    app.run(debug=True)
