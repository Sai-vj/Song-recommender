import os
import datetime
from flask import Flask, render_template, request, redirect, url_for, session
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = "secret123"

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
    client_id="e6eab89ebef44ae8ae039edede3e2eae",
    client_secret="32fe227f812a48968234f3b488a15db0",
    redirect_uri="http://127.0.0.1:5000/callback",
    scope="user-library-read user-top-read playlist-read-private"
)


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login")
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route("/callback")
def callback():
    token_info = sp_oauth.get_access_token(request.args["code"])
    session["token_info"] = token_info
    return redirect(url_for("recommend"))

@app.route("/recommend", methods=["GET", "POST"])
def recommend():
    token_info = session.get("token_info")
    if not token_info:
        return redirect(url_for("login"))

    sp = Spotify(auth=token_info["access_token"])

    playlists = []
    if request.method == "POST":
        mood = request.form.get("mood", "").lower()
        # Search playlists in Spotify
        results = sp.search(q=mood, type="playlist", limit=5)
        for p in results["playlists"]["items"]:
            playlists.append({
                "name": p["name"],
                "url": p["external_urls"]["spotify"]
            })
            # Save in DB
            entry = SearchHistory(mood=mood, playlist_name=p["name"], playlist_url=p["external_urls"]["spotify"])
            db.session.add(entry)
            db.session.commit()

        return render_template("result.html", mood=mood.capitalize(), playlists=playlists)

    return render_template("recommend.html")

@app.route("/history")
def history():
    records = SearchHistory.query.order_by(SearchHistory.timestamp.desc()).all()
    return render_template("history.html", records=records)

if __name__ == "__main__":
    app.run(debug=True)
