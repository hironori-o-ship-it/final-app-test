# 1. ベースとなる公式のPythonイメージを指定します
FROM python:3.11-slim

# 2. コンテナ内の作業ディレクトリを設定します
WORKDIR /app

# 3. 必要なライブラリの一覧ファイルをコピーします
COPY requirements.txt requirements.txt

# 4. requirements.txtに書かれたライブラリをインストールします
RUN pip install --no-cache-dir -r requirements.txt

# 5. アプリケーションのコード一式をコピーします
COPY . .

# 6. このコンテナが起動したときに実行するコマンドを指定します
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]