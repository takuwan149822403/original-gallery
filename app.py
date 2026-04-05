from flask import Flask, render_template, request, redirect, url_for, Response, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from pathlib import Path
from werkzeug.exceptions import HTTPException

# 定義
app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "instance" / "gallery.db"

# instance フォルダを起動時に必ず作る
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB

db = SQLAlchemy(app)

# データベース
#name:Picture
#id:ID           一意に採番
#title:          画像のタイトル（100字）
#description:    説明文（可変長）
#image_data:     画像データ（バイナリ）
#image_mime:     拡張子情報
#image_filename: ファイル名
#created_at:     作成日
#updated_at:     更新日
class Picture(db.Model):
    __tablename__ = "pictures"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_data = db.Column(db.LargeBinary, nullable=False)
    image_mime = db.Column(db.String(50), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)


@app.route("/")
def main_page():
    """メインページを表示し、登録済み画像を新しい順で一覧表示する。"""
    pictures = Picture.query.order_by(Picture.created_at.desc()).all()
    return render_template("main_page.html", pictures=pictures)


@app.route("/pictures/new", methods=["GET", "POST"])
def create_picture():
    """register.htmlより入力されたデータをもとにDBに登録する"""
    # リクエストの内容を確認
    if request.method == "POST":
        image_file = request.files.get("image")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        # 画像が選択されていない場合
        if not image_file or image_file.filename == "":
            abort(400, description="画像を選択してください。")
        # タイトルが選択されていない場合
        if not title:
            abort(400, description="タイトルを入力してください。")
        # Pictureクラスを作成
        picture = Picture(
            title=title,
            description=description,
            image_data=image_file.read(),
            image_mime=image_file.mimetype or "application/octet-stream",
            image_filename=image_file.filename
        )
        # DBに登録(失敗したらロールバック)
        try:
            db.session.add(picture)
            db.session.commit()
        except Exception:
            db.session.rollback
            app.logger.exception("画像登録に失敗しました。")
            abort(500)

        return redirect(url_for("picture_detail", picture_id=picture.id))

    return render_template("register.html")


@app.route("/pictures/<int:picture_id>")
def picture_detail(picture_id):
    """DBから取得したデータを表示する(なければ404を返す)"""
    picture = Picture.query.get_or_404(picture_id)
    return render_template("picture_detail.html", picture=picture)


@app.route("/pictures/<int:picture_id>/image")
def picture_image(picture_id):
    """pictures配下にDBから取得したイメージを配置する"""
    picture = Picture.query.get_or_404(picture_id)
    return Response(picture.image_data, mimetype=picture.image_mime)

@app.route("/pictures/<int:picture_id>/delete", methods=["POST"])
def delete_picture(picture_id):
    """pictures配下のデータを選択してDBから削除する"""
    picture = Picture.query.get_or_404(picture_id)

    # デリート
    try:
        db.session.delete(picture)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("削除に失敗しました。")
        abort(500)
    
    return redirect(url_for("main_page"))

@app.route("/pictures/delete-all", methods=["POST"])
def delete_all_pictures():
    """テスト用に登録済み画像データを全件削除する。"""
    pictures = Picture.query.all()

    try:
        for picture in pictures:
            db.session.delete(picture)

        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("削除に失敗しました。")
        abort(500)

    return redirect(url_for("main_page"))

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    """HTTP例外を受け取り、4xx系は共通エラーページで返す。"""
    if 400 <= e.code < 500:
        return render_template(
            "4xx.html",
            status_code=e.code,
            error_name=e.name,
            description=e.description
        ), e.code

    return e


@app.errorhandler(Exception)
def handle_exception(e):
    """想定外の例外を受け取り、5xx系の共通エラーページで返す。"""
    db.session.rollback()
    app.logger.exception("予期しないエラーが発生しました。")

    return render_template(
        "5xx.html",
        status_code=500,
        error_name="Internal Server Error",
        description="サーバー内部でエラーが発生しました。"
    ), 500

# アプリ起動時にDBを作成
with app.app_context():
        db.create_all()

# アプリを起動
if __name__ == "__main__":
    app.run(debug=True)