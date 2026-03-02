from flask import Flask, render_template, request, send_file, Response
import os, shutil
from flask import Response
from scraper import scrape

app = Flask(__name__)

logs = []

def log_stream():
    for line in logs:
        yield f"data: {line}\n\n"

@app.route("/stream")
def stream():
    return Response(log_stream(), mimetype="text/event-stream")

def add_log(message):
    logs.append(message)

DOWNLOADS_FOLDER = os.path.join("static", "downloads")
os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        link = request.form.get("link")
        if not link:
            return render_template("index.html", error="Please enter a link.")

        # Run scraper
        df, excel_path, images_folder = scrape(link)

        # Create ZIP of images
        zip_path = images_folder + ".zip"
        shutil.make_archive(images_folder, 'zip', images_folder)

        return render_template(
            "index.html",
            excel_file=os.path.basename(excel_path),
            zip_file=os.path.basename(zip_path)
        )

    return render_template("index.html")

@app.route("/download/<filename>")
def download(filename):
    file_path = os.path.join(DOWNLOADS_FOLDER, filename)
    return send_file(file_path, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
