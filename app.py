from flask import Flask, render_template, request, redirect, url_for, Response, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from pathlib import Path
from werkzeug.exceptions import HTTPException
from pytz import timezone
import csv

# 定義(サンプルデータ挿入関数呼び出し済フラグ)
sample_data_loaded = False

# 定義
app = Flask(__name__)
JST = timezone('Asia/Tokyo')

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "instance" / "gallery.db"

# instance フォルダを起動時に必ず作る
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB

db = SQLAlchemy(app)

# 中間テーブル: PictureとTagの多対多関係
picture_tag = db.Table(
    "picture_tag",
    db.Column("picture_id", db.Integer, db.ForeignKey("pictures.id", ondelete="CASCADE"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
)

# データベース
#name:Tag
#id:ID           一意に採番
#name:           タグ名（50字）
#color:          タグの色（HEXカラーコード）
class Tag(db.Model):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    color = db.Column(db.String(7), nullable=False, default="#808080")  # HEXカラー


# データベース
#name:Picture
#id:ID           一意に採番
#title:          画像のタイトル（100字）
#description:    説明文（可変長）
#image_data:     画像データ（バイナリ）
#image_mime:     拡張子情報
#image_filename: ファイル名
#created_at:     作成日(日本時間)
#updated_at:     更新日(日本時間)
#tags:           複数のタグ
class Picture(db.Model):
    __tablename__ = "pictures"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_data = db.Column(db.LargeBinary, nullable=False)
    image_mime = db.Column(db.String(50), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False)
    # created_atは登録時に自動で現在日時をセット、updated_atは更新のたびに自動で現在日時をセットする
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(JST))
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=lambda: datetime.now(JST))
    # tagsはTagクラスと多対多の関係を持つ。picture_tagテーブルを中間テーブルとして使用する。
    # タグが削除されたら関連するpicture_tagのレコードも削除されるように、cascade="all, delete"を指定する。
    tags = db.relationship("Tag", secondary=picture_tag, backref="pictures", cascade="all, delete")


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
        tags_input = request.form.get("tags", "").strip()
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
        
        # タグを処理（カンマ区切り）
        if tags_input:
            tag_names = [t.strip() for t in tags_input.split(",") if t.strip()]
            for tag_name in tag_names:
                tag = Tag.query.filter_by(name=tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.session.add(tag)
                picture.tags.append(tag)
        
        # DBに登録(失敗したらロールバック)
        try:
            db.session.add(picture)
            db.session.commit()
        except Exception:
            db.session.rollback()
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

@app.route("/pictures/<int:picture_id>/update", methods=["GET", "POST"])
def update_picture(picture_id):
    """pictures配下のデータを選択してDBから更新する"""
    picture = Picture.query.get_or_404(picture_id)

    if request.method == "POST":
        # タイトル、説明文が変更されていれば更新用に保持する
        if request.form.get("title").strip() != picture.title:
            title = request.form.get("title", "").strip()
        else:
            title = None

        if request.form.get("description").strip() != picture.description:
            description = request.form.get("description", "").strip()
        else:
            description = None

        # タグは一つでも入っていれば保持する(追加可否の判定はfor文で行うため)
        if request.form.get("tags", "").strip() != "":
            tags_input = request.form.get("tags", "").strip()
        else:
            tags_input = None

        # ページから何も入力されていない場合は400を返す
        if not title and not description and not tags_input:
            abort(400, description="少なくとも一つのフィールドを入力してください。")

        # タイトルと説明文を更新
        if title:
            picture.title = title
        if description:
            picture.description = description

        # タグを処理
        # タグをカンマ区切りで分割してリスト化
        if tags_input is not None:
            tag_names = [t.strip() for t in tags_input.split(",") if t.strip()]
            new_tags = []
            for tag_name in tag_names:
                # タグが既に存在するか確認し、なければ新規作成してDBに追加
                tag = Tag.query.filter_by(name=tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.session.add(tag)
                new_tags.append(tag)

            # 既存のタグを新しいタグリストに置き換える
            picture.tags = new_tags

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("更新に失敗しました。")
            abort(500)

        return redirect(url_for("picture_detail", picture_id=picture.id))

    return render_template("update.html", picture=picture)

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

def load_sample_data():
    """起動時にサンプルデータを挿入する"""
    # 多重呼び出し防止
    global sample_data_loaded
    if sample_data_loaded:
        print("サンプルデータはすでに挿入されています。")
        return
    
    # すでにデータがあれば削除
    print("サンプルデータの挿入を開始します。")
    if Picture.query.first():
        pictures = Picture.query.all()
        for picture in pictures:
            db.session.delete(picture)
        db.session.commit()
        print("既存のサンプルデータを削除しました。")

    data_file = BASE_DIR / "data" / "data_txt.txt"
    if not data_file.exists():
        return

    csv_dir = data_file.parent  # CSVファイルが置いてあるディレクトリ

    with open(data_file, "r", encoding="utf-8") as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            print(f"サンプルデータを挿入中: {row['title']}")
            # OSに依存しないパスの正規化を行う。CSV内のパスは相対パスで、OSによって
            # 区切り文字が異なる可能性があるため、両方に対応できるようにする。
            raw_path = row["data_path"].strip()
            normalized_path = raw_path.replace("\\", "/").removeprefix("./")
            img_path = csv_dir / Path(normalized_path)

            if not img_path.exists():
                app.logger.warning(
                    "サンプル画像が見つかりません: raw=%s resolved=%s",
                    raw_path,
                    img_path
                )
                continue

            with open(img_path, "rb") as img_file:
                image_data = img_file.read()

            created_str = row["created_at"]
            created_at = datetime.strptime(created_str, "%Y%m%d").replace(
                tzinfo=JST
            )

            updated_at = None
            if row["updated_at"] and row["updated_at"] != "None":
                updated_str = row["updated_at"]
                updated_at = datetime.strptime(updated_str, "%Y%m%d").replace(
                    tzinfo=JST
                )

            picture = Picture(
                title=row["title"],
                description=row["description"],
                image_data=image_data,
                image_mime="image/jpeg",
                image_filename=img_path.name,
                created_at=created_at,
                updated_at=updated_at,
            )

            if row["tags_input"]:
                tag_names = [t.strip() for t in row["tags_input"].split(",") if t.strip()]
                for tag_name in tag_names:
                    tag = Tag.query.filter_by(name=tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name)
                        db.session.add(tag)
                    picture.tags.append(tag)

            db.session.add(picture)

    db.session.commit()
    sample_data_loaded = True
    print("サンプルデータの挿入が完了しました。")

# アプリ起動時にDBを作成
with app.app_context():
    db.create_all()
    load_sample_data()

# アプリを起動
if __name__ == "__main__":
    app.run(debug=True)