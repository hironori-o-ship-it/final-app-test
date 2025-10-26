from flask import Flask
import os

app = Flask(__name__)

@app.route("/")
def hello_world():
  """Renderで起動するWebサービスのエンドポイントです。"""
  return "<h1>FINAL SUCCESS!</h1><p>このメッセージが表示されれば、公開は完了です。</p>"

if __name__ == "__main__":
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)
