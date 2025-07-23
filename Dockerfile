FROM python:3.11-slim
ENV LANG=ja_JP.UTF-8
ENV LC_ALL=ja_JP.UTF-8
# システムの依存関係をインストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    mecab \
    libmecab-dev \
    mecab-ipadic-utf8 \
    mecab-utils \
    swig \
    build-essential \
    wget \
    unzip \
    git \
    curl \
    file \
    sudo \
    fonts-noto-cjk \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリを設定
WORKDIR /app

# 出力ディレクトリを作成
RUN mkdir -p /app/output

# ボリュームを定義
VOLUME ["/app"]

# MeCabの設定ファイルのパスを修正
RUN mkdir -p /usr/local/etc && \
    if [ -f /etc/mecabrc ]; then \
      cp /etc/mecabrc /usr/local/etc/; \
    fi

# 必要なファイルをコピー
COPY requirements.txt .
COPY dict.csv .

# Pythonの依存関係をインストール
RUN pip install --no-cache-dir -r requirements.txt

# NEologd辞書のインストール
RUN git clone --depth 1 https://github.com/neologd/mecab-ipadic-neologd.git && \
    cd mecab-ipadic-neologd && \
    ./bin/install-mecab-ipadic-neologd -n -y && \
    cd /app && \
    rm -rf mecab-ipadic-neologd

# dict-indexコマンドを検索してユーザー辞書をコンパイル
RUN echo "ユーザー辞書をコンパイルします" && \
    DICT_INDEX_PATH=$(find / -name mecab-dict-index -type f 2>/dev/null | head -n 1) && \
    if [ -n "$DICT_INDEX_PATH" ]; then \
        $DICT_INDEX_PATH -d /usr/share/mecab/dic/ipadic -u /app/user.dic -f utf-8 -t utf-8 dict.csv && \
        echo "辞書コンパイル完了"; \
    else \
        echo "mecab-dict-indexが見つかりませんでした"; \
        echo "ユーザー辞書なしで続行します"; \
    fi

# デフォルトコマンド
ENTRYPOINT ["python"]
CMD ["--help"]
