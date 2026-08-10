FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY skillforge ./skillforge
COPY frontend ./frontend
# 向量化预设种子：放到非卷路径 /app/preset，启动时按需拷入 DATA_DIR。
# （避免 compose 将 DATA_DIR 覆盖为 /data 并挂载空卷时，镜像内预设被卷遮蔽导致 embedding 分支 FileNotFoundError）
COPY data/vectorizer.local-st.json /app/preset/vectorizer.local-st.json

ENV SKILLS_DIRS=/root/.workbuddy/skills
ENV DATA_DIR=/app/data
VOLUME ["/root/.workbuddy/skills", "/app/data"]

EXPOSE 8000

# 启动时确保 DATA_DIR 存在且含向量化预设：
# - 应用硬编码从 /app/data/vectorizer.local-st.json 读取预设（忽略 DATA_DIR）；
# - compose 把 DATA_DIR 覆盖为 /data 并挂载空卷，会把镜像内 /app/data 内容遮蔽；
# 因此在容器启动（卷已挂载后）从 /app/preset 拷入 /app/data 与 $DATA_DIR 两处，两种姿势都覆盖。
CMD ["sh", "-c", "mkdir -p /app/data \"$DATA_DIR\"; if [ -f /app/preset/vectorizer.local-st.json ]; then [ ! -f /app/data/vectorizer.local-st.json ] && cp /app/preset/vectorizer.local-st.json /app/data/; [ ! -f \"$DATA_DIR/vectorizer.local-st.json\" ] && cp /app/preset/vectorizer.local-st.json \"$DATA_DIR/\"; fi; exec uvicorn skillforge.server:app --host 0.0.0.0 --port 8000"]
